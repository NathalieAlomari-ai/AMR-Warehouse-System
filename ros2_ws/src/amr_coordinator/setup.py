import os
from glob import glob
from setuptools import setup

package_name = 'amr_coordinator'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Nathalie',
    maintainer_email='nathalieeee2004@gmail.com',
    description='Mission coordinator FSM: sequences Nav2, lift, stepper, pump and '
                'vision for one warehouse pick-and-place cycle.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'coordinator_node = amr_coordinator.coordinator_node:main',
            'vision_stub = amr_coordinator.vision_stub:main',
        ],
    },
)
