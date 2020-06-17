#!/usr/bin/env python

#!/usr/bin/env python

# Copyright (c) Facebook, Inc. and its affiliates.

# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import print_function

import PyKDL as kdl
import numpy as np
import copy
import rospy
import threading
import tf
import actionlib
from geometry_msgs.msg import Twist
from kdl_parser_py.urdf import treeFromParam
from sensor_msgs.msg import JointState
from trac_ik_python import trac_ik

from pyrobot_bridge.srv import *
import moveit_commander


from pyrobot_bridge.msg import (
    MoveitAction,
    MoveitGoal,
)
from actionlib_msgs.msg import GoalStatus, GoalStatusArray
from moveit_msgs.msg import ExecuteTrajectoryAction


class MoveitInterface(object):
    """Interfaces moveit tools to pyrobot"""

    def __init__(self):
        self.init_node = False
        
        rospy.init_node("pyrobot_moveit")

        self.lock = threading.RLock()

        self.moveit_server_ = actionlib.SimpleActionServer(
            "/pyrobot/moveit_server", 
            MoveitAction,
            execute_cb=self.moveit_cb,
            auto_start=False,
        )
        self.moveit_server_.start()    
        self.execution_state = GoalStatus.PENDING    
        rospy.Subscriber(
            "/execute_trajectory/status", GoalStatusArray, self._traj_execution_state_cb
        )
        rospy.sleep(0.1)  # Ensures client spins up properly

        rospy.spin()


    def _init_moveit(self):

        """
        Initialize moveit and setup move_group object
        """
        self.moveit_planner = rospy.get_param("pyrobot/moveit_planner")
        moveit_commander.roscpp_initialize(sys.argv)
        mg_name = rospy.get_param("pyrobot/move_group_name")
        self.moveit_group = moveit_commander.MoveGroupCommander(mg_name)
        self.moveit_group.set_planner_id(self.moveit_planner)
        self.scene = moveit_commander.PlanningSceneInterface()


        self.init_node = True    

    def _traj_execution_state_cb(self, msg):

        self.lock.acquire()
        if len(msg.status_list) < 1:
            self.execution_state = GoalStatus.PENDING
        else:
            self.execution_state = msg.status_list[0].status
        self.lock.release()

    def get_execution_state(self):
         self.lock.acquire()
         state = self.execution_state
         self.lock.release()
         return state
    def _compute_plan(self, target_joint):
        """
        Computes motion plan to achieve desired target_joint
        :param target_joint: list of length #of joints, angles in radians
        :type target_joint: np.ndarray
        :return: Computed motion plan
        :rtype: moveit_msgs.msg.RobotTrajectory
        """
        # TODO Check if target_joint is valid

        if isinstance(target_joint, np.ndarray):
            target_joint = target_joint.tolist()
        self.moveit_group.set_joint_value_target(target_joint)
        rospy.loginfo('Moveit Motion Planning...')
        return self.moveit_group.plan()

    def _execute_plan(self, plan, wait=False):
        """
        Executes plan on arm controller
        :param plan: motion plan to execute
        :param wait: True if blocking call and will return after
                     target_joint is achieved, False otherwise
        :type plan: moveit_msgs.msg.RobotTrajectory
        :type wait: bool
        :return: True if arm executed plan, False otherwise
        :rtype: bool
        """
        result = False

        if len(plan.joint_trajectory.points) < 1:
            rospy.logwarn('No motion plan found. No execution attempted')
            self.moveit_server_.set_aborted()
        else:
            rospy.loginfo('Executing...')
            result = self.moveit_group.execute(plan, wait=wait)
        return result



    def _set_joint_positions(self, goal):
        try:
            moveit_plan = self._compute_plan(goal.values)
            self._execute_plan(moveit_plan, wait=False)
        except:
            rospy.logerr("PyRobot-Moveit:Unexpected error in move_ee_xyx")
            self.moveit_server_.set_aborted()
            return

        status =  self.get_execution_state()
        while status != GoalStatus.SUCCEEDED:
            rospy.logerr(status)
            if self.moveit_server_.is_preempt_requested():
                rospy.loginfo("Preempted the Moveit execution by PyRobot")
                self.moveit_group.stop()
                self.moveit_server_.set_preempted()
                return
            if status == GoalStatus.ABORTED or status == GoalStatus.PREEMPTED:
                rospy.loginfo("Moveit trajectory execution aborted.")
                self.moveit_server_.set_aborted()
                return
            status =  self.get_execution_state()
        self.moveit_server_.set_succeeded()
        rospy.logwarn("Done set _joint pos")

    def _move_ee_xyz(self, goal):
        try:
            (plan, fraction) = self.moveit_group.compute_cartesian_path(
                goal.waypoints,  # waypoints to follow
                goal.eef_step,  # eef_step
                0.0)  # jump_threshold
            self._execute_plan(plan, wait=False)
        except:
            rospy.logerr("PyRobot-Moveit:Unexpected error in move_ee_xyx")
            self.moveit_server_.set_aborted()
            return
                
        status =  self.get_execution_state()
        while status != GoalStatus.SUCCEEDED:
            rospy.logwarn(status)
            if self.moveit_server_.is_preempt_requested():
                rospy.loginfo("Preempted the Moveit execution by PyRobot")
                self.moveit_group.stop()
                self.moveit_server_.set_preempted()
                return
            if status == GoalStatus.ABORTED or status == GoalStatus.PREEMPTED:
                rospy.loginfo("Moveit trajectory execution aborted.")
                self.moveit_server_.set_aborted()
                return
            status =  self.get_execution_state()
        self.moveit_server_.set_succeeded()

        rospy.logwarn("Done")

    def moveit_cb(self, goal):
        
        if not self.init_node:
            self._init_moveit()

        if goal.action_type == "set_joint_positions":
            self._set_joint_positions(goal)
        elif goal.action_type == "move_ee_xyz":
            self._move_ee_xyz(goal)
        else:
            rospy.logerr("Invalid PyRobot-Moveit Action Name, {}".format(goal.action_type))
            self.moveit_server_.set_aborted()

        



if __name__ == "__main__":
    server = MoveitInterface()