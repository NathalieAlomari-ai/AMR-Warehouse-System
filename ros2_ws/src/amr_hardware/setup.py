from setuptools import setup

package_name = 'amr_hardware'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Nathalie',
    maintainer_email='nathalieeee2004@gmail.com',
    description='Serial bridge between the Raspberry Pi ROS 2 stack and the Teensy 4.1 motor controller.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'serial_bridge_node = amr_hardware.serial_bridge_node:main',
        ],
    },
)
