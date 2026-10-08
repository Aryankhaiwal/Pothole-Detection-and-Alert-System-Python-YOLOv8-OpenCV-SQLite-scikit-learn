from ultralytics import YOLO
model = YOLO('pothole_model.pt')
model.predict(r"C:\Users\aryan\Videos\Screen Recordings\download.mp4", show=True, conf=0.4)