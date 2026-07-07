"""
vision_stub.py — stand-in for the real YOLO vision node
=======================================================

Lets you run and test the ENTIRE mission (Nav2 → lift → grip → drop → home)
before Abdullah's YOLO pipeline is deployed on the Jetson. It speaks the exact
same ROS contract the real vision node will, so swapping the real one in later
is a drop-in replacement — no coordinator change.

Contract it implements
───────────────────────
  subscribe /vision/request (std_msgs/String): "SHELF_QR" | "BOX_QR"
  publish   /vision/result  (std_msgs/String): "OK <sku>" | "FAIL"

For a BOX_QR request it also mimics the real node's job of centring the
suction cup: it streams a few "SERVO <deg>" commands to /aux/command (the same
single-serial-owner path the real servo loop uses) before replying "OK".

Parameters
──────────
  respond_delay (float, s)  : fake processing time before replying   [0.4]
  fail_shelf   (bool)       : reply FAIL to SHELF_QR (test the abort) [False]
  fail_box     (bool)       : reply FAIL to BOX_QR                    [False]
  fake_sku     (str)        : SKU string returned on success   ["SKU-TEST-01"]
"""

import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class VisionStub(Node):

    def __init__(self):
        super().__init__('vision_stub')

        self.declare_parameter('respond_delay', 0.4)
        self.declare_parameter('fail_shelf', False)
        self.declare_parameter('fail_box', False)
        self.declare_parameter('fake_sku', 'SKU-TEST-01')

        self._aux_pub = self.create_publisher(String, '/aux/command', 10)
        self._result_pub = self.create_publisher(String, '/vision/result', 10)
        self.create_subscription(String, '/vision/request', self._request_cb, 10)

        self.get_logger().warn(
            'vision_stub active — NO CAMERA. Replace with the real YOLO node '
            'on the Jetson for production.')

    def _request_cb(self, msg: String) -> None:
        request = msg.data.strip()
        self.get_logger().info(f'request: {request}')

        delay = self.get_parameter('respond_delay').get_parameter_value().double_value
        time.sleep(delay)   # pretend to run detection

        if request == 'SHELF_QR':
            if self.get_parameter('fail_shelf').get_parameter_value().bool_value:
                return self._reply('FAIL')
            return self._reply(f'OK {self._sku()}')

        if request == 'BOX_QR':
            if self.get_parameter('fail_box').get_parameter_value().bool_value:
                return self._reply('FAIL')
            self._fake_centering()          # stream a few SERVO nudges, then OK
            return self._reply(f'OK {self._sku()}')

        self.get_logger().warn(f'unknown vision request "{request}" — replying FAIL')
        self._reply('FAIL')

    def _fake_centering(self) -> None:
        """Mimic the real servo-centring loop converging to centred (SERVO 0)."""
        for deg in (2.0, 1.0, 0.3, 0.0):
            self._aux_pub.publish(String(data=f'SERVO {deg:.2f}'))
            self.get_logger().info(f'→ aux: SERVO {deg:.2f}')
            time.sleep(0.1)

    def _sku(self) -> str:
        return self.get_parameter('fake_sku').get_parameter_value().string_value

    def _reply(self, result: str) -> None:
        self.get_logger().info(f'result: {result}')
        self._result_pub.publish(String(data=result))


def main(args=None):
    rclpy.init(args=args)
    node = VisionStub()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
