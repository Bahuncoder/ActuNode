class Robot:
    def __init__(self, robot_id: str):
        self.robot_id = robot_id

        self.x = 0
        self.y = 0
       
        self.battery = 100
       
        self.state = "IDLE"


    def move(self, target_x: float, target_y: float) -> None:
        self.state = "MOVING"

        self.x  = target_x
        self.y  = target_y
        
        self.battery -= 1
    
    def stop(self):
        self.state = "IDLE"
  
    def status(self):
        print(
            f"{self.robot_id} | "
            f"{self.state} | "
            f"x={self.x} y={self.y} | "
            f"battery={self.battery}%"
        )


