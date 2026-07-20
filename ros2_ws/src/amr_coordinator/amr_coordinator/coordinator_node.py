"""
coordinator_node.py — AMR warehouse pick-and-place mission coordinator
======================================================================

This node is the single brain that sequences one full warehouse mission:
drive to a shelf, confirm it, raise the lift, let vision centre the suction
cup, grip the box, retract, drive to the drop-off, release, and return home.

Why a plain async FSM (not smach / BehaviorTree.CPP)
────────────────────────────────────────────────────
The mission is *linear with wait-points* — a numbered checklist, not a
reactive tree with fallbacks. A hand-written state machine is the least code,
the easiest for the team to read, and the easiest to debug. If reactive
recovery behaviour is needed later it ports cleanly to a BT; there is no
reason to pay that complexity now.

How it talks to the hardware (single-serial-owner rule)
───────────────────────────────────────────────────────
This node NEVER opens the serial port. Every low-level action is a string
published to serial_bridge_node, which is the only process that owns
/dev/ttyACM0:

  publish /aux/command (std_msgs/String):
      "LIFT <mm>"  "PICK"  "DROP"  "STEP EXT"  "STEP RET"  "PUMP ON"  "PUMP OFF"  "STOP"
      (PICK/DROP move the lift to Zahra's firmware-owned, bench-calibrated pick/
      drop heights — see PICK_LIFT_MM/DROP_LIFT_MM in firmware/integration/src/
      Config.h — so this node no longer needs to know or configure the actual mm.)
  wait on /aux/status (std_msgs/String) for the matching completion event:
      "EVT LIFT DONE"  "EVT STEP DONE"  "EVT PUMP ON"  "EVT PUMP OFF"
      "EVT FAULT <what>"   ← aborts the mission

Vision is decoupled the same way (so YOLO on the Jetson can arrive later):

  publish /vision/request (std_msgs/String): "SHELF_QR" | "BOX_QR"
  wait on /vision/result (std_msgs/String):  "OK <sku>" | "FAIL"

For BOX_QR the vision node is responsible for centring the suction cup
itself — the robot has no cup servo, so it rotates the whole robot by
publishing Twist to /cmd_vel_vision (twist_mux priority 50, above Nav2) and
only replies "OK" once aligned. The coordinator treats confirm+centre as one
request. The vision_stub node satisfies this same contract without a camera.

Concurrency model
─────────────────
A MultiThreadedExecutor spins the ROS callbacks while the mission itself runs
in a background worker thread, so the sequential checklist can be written as
straight-line blocking code (navigate → wait → command → wait …) while
subscriptions and the Nav2 action feedback keep flowing. Every callback uses
a ReentrantCallbackGroup so nothing deadlocks against the action client.
"""

import math
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from std_msgs.msg import String, Empty


class MissionAbort(Exception):
    """Raised inside the mission thread to unwind to a safe stop."""


class CoordinatorNode(Node):

    def __init__(self):
        super().__init__('amr_coordinator')

        # ── Named locations: [x, y, yaw_deg] in the map frame ────────────────
        # Override in a launch file / params yaml once the map is surveyed.
        self.declare_parameter('shelf_a',  [2.0, 0.0, 0.0])
        self.declare_parameter('dropoff',  [0.0, 2.0, 90.0])
        self.declare_parameter('home',     [0.0, 0.0, 0.0])

        # ── Lift heights ──────────────────────────────────────────────────────
        # Pick/drop heights are no longer a parameter here — the firmware owns
        # the bench-calibrated PICK_LIFT_MM/DROP_LIFT_MM values (Config.h) and
        # this node just says "PICK" / "DROP". Only the transit (fully down)
        # height stays a parameter, since "LIFT 0" is also the lift's re-home path.
        self.declare_parameter('lift_down_mm',    0)     # fully retracted / home

        # ── Timeouts (s) ─────────────────────────────────────────────────────
        self.declare_parameter('nav_timeout',    180.0)
        self.declare_parameter('lift_timeout',    30.0)
        self.declare_parameter('step_timeout',    20.0)
        self.declare_parameter('pump_timeout',     5.0)
        self.declare_parameter('vision_timeout',  30.0)

        self.declare_parameter('auto_start', False)   # run one mission on boot

        self._cbg = ReentrantCallbackGroup()

        # ── Aux-hardware channel ─────────────────────────────────────────────
        self._aux_pub = self.create_publisher(String, '/aux/command', 10)
        self.create_subscription(
            String, '/aux/status', self._aux_status_cb, 10,
            callback_group=self._cbg)
        self._aux_cv = threading.Condition()
        self._aux_events: list[str] = []

        # ── Vision handshake channel ─────────────────────────────────────────
        self._vision_pub = self.create_publisher(String, '/vision/request', 10)
        self.create_subscription(
            String, '/vision/result', self._vision_result_cb, 10,
            callback_group=self._cbg)
        self._vision_cv = threading.Condition()
        self._vision_result: str | None = None

        # ── Mission trigger: `ros2 topic pub /mission/start std_msgs/Empty {}`
        self.create_subscription(
            Empty, '/mission/start', self._start_cb, 10,
            callback_group=self._cbg)
        self._mission_lock = threading.Lock()   # guards against re-entrancy

        # ── Nav2 ─────────────────────────────────────────────────────────────
        self._nav_client = ActionClient(
            self, NavigateToPose, '/navigate_to_pose',
            callback_group=self._cbg)

        self.get_logger().info(
            'amr_coordinator ready. Trigger a mission with:  '
            'ros2 topic pub --once /mission/start std_msgs/msg/Empty "{}"')

        if self.get_parameter('auto_start').get_parameter_value().bool_value:
            threading.Thread(target=self._run_mission_guarded, daemon=True).start()

    # ═════════════════════════════════════════════════════════════════════════
    #  Subscription callbacks (feed the mission thread)
    # ═════════════════════════════════════════════════════════════════════════

    def _aux_status_cb(self, msg: String) -> None:
        with self._aux_cv:
            self._aux_events.append(msg.data.strip())
            self._aux_cv.notify_all()

    def _vision_result_cb(self, msg: String) -> None:
        with self._vision_cv:
            self._vision_result = msg.data.strip()
            self._vision_cv.notify_all()

    def _start_cb(self, _msg: Empty) -> None:
        threading.Thread(target=self._run_mission_guarded, daemon=True).start()

    # ═════════════════════════════════════════════════════════════════════════
    #  Blocking helpers used by the mission thread
    # ═════════════════════════════════════════════════════════════════════════

    def _send_aux(self, command: str) -> None:
        self.get_logger().info(f'→ aux: {command}')
        self._aux_pub.publish(String(data=command))

    def _wait_for_aux(self, prefix: str, timeout: float) -> None:
        """Block until an /aux/status line starts with `prefix`.

        Raises MissionAbort on 'EVT FAULT …' or on timeout.
        """
        deadline = time.monotonic() + timeout
        with self._aux_cv:
            self._aux_events.clear()          # only consider events from now on
            while True:
                for evt in self._aux_events:
                    if evt.startswith('EVT FAULT'):
                        raise MissionAbort(f'firmware fault: {evt}')
                    if evt.startswith(prefix):
                        self.get_logger().info(f'✓ {evt}')
                        return
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise MissionAbort(f'timeout waiting for "{prefix}"')
                self._aux_cv.wait(remaining)

    def _aux_step(self, command: str, done_prefix: str, timeout: float) -> None:
        """Send an aux command and block on its completion event."""
        with self._aux_cv:
            self._aux_events.clear()
        self._send_aux(command)
        self._wait_for_aux(done_prefix, timeout)

    def _confirm_vision(self, request: str, timeout: float) -> str:
        """Ask vision to confirm a QR (and, for BOX_QR, centre the cup).

        Returns the SKU string; raises MissionAbort on FAIL/timeout.
        """
        self.get_logger().info(f'→ vision: {request}')
        with self._vision_cv:
            self._vision_result = None
            self._vision_pub.publish(String(data=request))
            deadline = time.monotonic() + timeout
            while self._vision_result is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise MissionAbort(f'vision timeout on "{request}"')
                self._vision_cv.wait(remaining)
            result = self._vision_result
        if result.startswith('OK'):
            self.get_logger().info(f'✓ vision {request}: {result}')
            return result[2:].strip()
        raise MissionAbort(f'vision rejected "{request}": {result}')

    def _navigate_to(self, name: str, timeout: float) -> None:
        """Drive to a named location parameter; raises MissionAbort on failure."""
        x, y, yaw_deg = self.get_parameter(name).get_parameter_value().double_array_value
        self.get_logger().info(f'→ Nav2: {name} = ({x:.2f}, {y:.2f}, {yaw_deg:.0f}°)')

        if not self._nav_client.wait_for_server(timeout_sec=10.0):
            raise MissionAbort('Nav2 action server /navigate_to_pose unavailable')

        goal = NavigateToPose.Goal()
        goal.pose = self._make_pose(x, y, math.radians(yaw_deg))

        goal_handle = self._await_future(
            self._nav_client.send_goal_async(goal), 15.0)
        if goal_handle is None or not goal_handle.accepted:
            raise MissionAbort(f'Nav2 rejected goal for {name}')

        result = self._await_future(goal_handle.get_result_async(), timeout)
        if result is None:
            goal_handle.cancel_goal_async()
            raise MissionAbort(f'Nav2 timeout reaching {name}')
        if result.status != GoalStatus.STATUS_SUCCEEDED:
            raise MissionAbort(f'Nav2 failed reaching {name} (status={result.status})')
        self.get_logger().info(f'✓ arrived at {name}')

    def _make_pose(self, x: float, y: float, yaw: float) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = float(x)
        pose.pose.position.y = float(y)
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def _await_future(self, future, timeout: float):
        """Block the mission thread on an rclpy future (executor spins elsewhere)."""
        done = threading.Event()
        future.add_done_callback(lambda _f: done.set())
        if not done.wait(timeout):
            return None
        return future.result()

    # ═════════════════════════════════════════════════════════════════════════
    #  The mission
    # ═════════════════════════════════════════════════════════════════════════

    def _run_mission_guarded(self) -> None:
        if not self._mission_lock.acquire(blocking=False):
            self.get_logger().warn('mission already running — ignoring trigger')
            return
        try:
            self._run_mission()
        except MissionAbort as e:
            self.get_logger().error(f'MISSION ABORTED: {e}')
            self._send_aux('STOP')          # e-stop aux hardware, hold position
        except Exception as e:  # noqa: BLE001 — last-resort safety net
            self.get_logger().error(f'MISSION CRASHED: {e!r}')
            self._send_aux('STOP')
        finally:
            self._mission_lock.release()

    def _run_mission(self) -> None:
        p = self.get_parameter
        down    = p('lift_down_mm').get_parameter_value().integer_value
        t_nav   = p('nav_timeout').get_parameter_value().double_value
        t_lift  = p('lift_timeout').get_parameter_value().double_value
        t_step  = p('step_timeout').get_parameter_value().double_value
        t_pump  = p('pump_timeout').get_parameter_value().double_value
        t_vis   = p('vision_timeout').get_parameter_value().double_value

        self.get_logger().info('════════ MISSION START ════════')

        # 1–3. Drive to shelf and confirm it is the right one.
        self._navigate_to('shelf_a', t_nav)
        self._confirm_vision('SHELF_QR', t_vis)

        # 4. Raise the lift to the firmware-owned pick height.
        self._aux_step('PICK', 'EVT LIFT DONE', t_lift)

        # 5. Confirm the box QR; vision centres the cup (streams SERVO itself).
        sku = self._confirm_vision('BOX_QR', t_vis)
        self.get_logger().info(f'picking SKU: {sku}')

        # 6–8. Extend cup, grip, retract box onto the robot.
        self._aux_step('STEP EXT', 'EVT STEP DONE', t_step)
        self._aux_step('PUMP ON',  'EVT PUMP ON',   t_pump)
        self._aux_step('STEP RET', 'EVT STEP DONE', t_step)

        # 9. Lower the lift for transit.
        self._aux_step(f'LIFT {down}', 'EVT LIFT DONE', t_lift)

        # 10. Drive to the drop-off bay.
        self._navigate_to('dropoff', t_nav)

        # 11. Drop sequence: raise to the firmware-owned drop height, extend,
        #     release vacuum, retract, lower.
        self._aux_step('DROP', 'EVT LIFT DONE', t_lift)
        self._aux_step('STEP EXT',  'EVT STEP DONE', t_step)
        self._aux_step('PUMP OFF',  'EVT PUMP OFF',  t_pump)
        self._aux_step('STEP RET',  'EVT STEP DONE', t_step)
        self._aux_step(f'LIFT {down}', 'EVT LIFT DONE', t_lift)

        # 12. Return home, ready for the next order.
        self._navigate_to('home', t_nav)

        self.get_logger().info('════════ MISSION COMPLETE ════════')


def main(args=None):
    rclpy.init(args=args)
    node = CoordinatorNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
