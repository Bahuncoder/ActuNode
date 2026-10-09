from simulator.robot import Robot

robot = Robot("robot_01")


robot.status()

robot.move(5, 3)
robot.status()

robot.move(10, 4)
robot.status()

robot.stop()
robot.status()
