#!/usr/bin/env python
import time
import numpy as np
import rospy

from geometry_msgs.msg import PoseArray
from blimp import BlimpEnv
from rotor_controller import RotorController
from mixer import BlimpMixer

EPISODE_LENGTH = 30*100

class ControlsFlyer():

    def __init__(self):
        self.env = BlimpEnv()
        self._create_pubs_subs()
        self.controller = RotorController()
        self.mixer = BlimpMixer()

        self.cnt=0

        self.local_position_target = np.array([0.0,0.0,0.0])
        self.local_position = np.array([0.0,0.0,0.0])
        self.local_velocity_target = np.array([0.0,0.0,0.0])
        self.local_velocity = np.array([0.0,0.0,0.0])
        self.local_acceleration_target = np.array([0.0,0.0,0.0])

        self.position_target_destination = np.array([0.0,0.0,0.0])
        self.attitude_target_destination = np.array([0.0,0.0,0.0])
        self.position_trajectory = []
        self.yaw_trajectory = []
        self.time_trajectory = []

        self.attitude = np.array([0.0,0.0,0.0])
        self.attitude_target = np.array([0.0,0.0,0.0])

        self.body_rate = np.array([0.0,0.0,0.0])
        self.body_rate_target = np.array([0.0,0.0,0.0])

        self.thrust_cmd = 0.0
        self.cmd_rotor = np.array([0.0,0.0,0.0,0.0])
        self.cmd_vtol = np.array([0.0,0.0,0.0,0.0])

    def _create_pubs_subs(self):
        rospy.Subscriber(
            "/machine_1/mpc_calculated/pose_traj",
            PoseArray,
            self.trajectory_callback)

    def trajectory_callback(self, msg):
        """
        15 waypoint for the next 3 secs

        geometry_msgs/Pose: 
        geometry_msgs/Point position
          float64 x
          float64 y
          float64 z
        geometry_msgs/Quaternion orientation
          float64 x
          float64 y
          float64 z
          float64 w

        :param msg:
        :return:
        """
        data=[]
        time_mult=1.0
        self.position_trajectory = []
        self.time_trajectory = []
        self.yaw_trajectory = []

        for i in range(15):
            x = msg.poses[i].position.x
            y = msg.poses[i].position.y
            z = msg.poses[i].position.z
            data.append([0.2*i, x, y, z])

        data = np.array(data)        

        current_time = time.time()
        for i in range(len(data[:,0])):
            self.position_trajectory.append(data[i,1:4])
            self.time_trajectory.append(data[i,0]*time_mult+current_time)
        for i in range(0,len(self.position_trajectory)-1):
            self.yaw_trajectory.append(np.arctan2(self.position_trajectory[i+1][1]-self.position_trajectory[i][1],self.position_trajectory[i+1][0]-self.position_trajectory[i][0]))
        self.yaw_trajectory.append(self.yaw_trajectory[-1])

    def position_controller(self):
        # (self.local_position_target,
        #  self.local_velocity_target,
        #  yaw_cmd) = self.controller.trajectory_control(
        #          self.position_trajectory,
        #          self.yaw_trajectory,
        #          self.time_trajectory, time.time())
        # self.attitude_target = np.array((0.0, 0.0, yaw_cmd))
        acceleration_cmd = self.controller.lateral_position_control(
                self.local_position_target[0:2],
                self.local_velocity_target[0:2],
                self.local_position[0:2],
                self.local_velocity[0:2])
        self.local_acceleration_target = np.array([acceleration_cmd[0],
                                                   acceleration_cmd[1],
                                                   0.0])

    def attitude_controller(self):
        self.thrust_cmd = self.controller.altitude_control(
                -self.local_position_target[2],
                -self.local_velocity_target[2],
                -self.local_position[2],
                -self.local_velocity[2],
                self.attitude,
                9.81)
        roll_pitch_rate_cmd = self.controller.roll_pitch_controller(
                self.local_acceleration_target[0:2],
                self.attitude,
                self.thrust_cmd)
        yawrate_cmd = self.controller.yaw_control(
                self.attitude_target[2],
                self.attitude[2])
        self.body_rate_target = np.array(
                [roll_pitch_rate_cmd[0], roll_pitch_rate_cmd[1], yawrate_cmd])

    def bodyrate_controller(self):
        moment_cmd = self.controller.body_rate_control(
                self.body_rate_target,
                self.body_rate)
        self.cmd_rotor = [moment_cmd[0],
                        moment_cmd[1],
                        moment_cmd[2],
                        self.thrust_cmd]

    def rotor_control_update(self, obs):
        self.position_controller()
        self.attitude_controller()
        self.bodyrate_controller()

    def actuation_update(self):
        self.action = self.mixer.mix(self.cmd_rotor, self.cmd_vtol)

    def unwrap_obs(self, obs):
        angle = obs[0:3]
        angular_velocity = obs[3:6]
        position = obs[6:9]
        velocity = obs[9:12]
        linear_acceleration = obs[12:15]
        target_angle = obs[15:18]
        target_position = obs[18:21]

        self.local_position = np.array(position)
        # self.local_position_target = np.array(target_position)
        self.local_position_target = 3
        self.local_velocity = np.array(velocity)
        self.attitude = np.array(angle)
        # self.attitude_target = np.array(target_angle)
        self.attitude_target = 0
        self.body_rate = np.array(angular_velocity)

    def start(self):
        time_step=0
        total_reward=0
        obs = self.env.reset()
        self.unwrap_obs(obs)

        while time_step < EPISODE_LENGTH:
            time_step+=1
            self.rotor_control_update(obs)
            self.actuation_update()
            obs, reward, done = self.env.step(self.action)
            self.unwrap_obs(obs)

            if time_step%100 == 0:
                total_reward+=reward
                print("----------------------------")
                print("action = %2.3f, %2.3f, %2.3f, %2.3f" % (self.action[0], self.action[1], self.action[2], self.action[3]))
                print("cmd[0] = %2.3f, cmd[1]=%2.3f, cmd[2]=%2.3f, cmd[3]=%2.3f" % (self.cmd_rotor[0],self.cmd_rotor[1],self.cmd_rotor[2],self.cmd_rotor[3]))
                print("target poisition = ", self.local_position_target)
                print("(x,y,z) = ", self.local_position)
                print("(phi,the,psi) = ", self.attitude - self.attitude_target)
                

        obs = self.env.reset()
        print("total reward = ", total_reward)

if __name__ == "__main__":
    drone = ControlsFlyer()
    time.sleep(2)
    drone.start()
