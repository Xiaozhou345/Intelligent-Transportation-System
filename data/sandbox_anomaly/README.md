# Sandbox Anomaly Dataset

This local folder is for tuning the road anomaly detector. Image/video data is
ignored by Git and should not be committed.

## Folders

- `clean_road/`: normal road images used to initialize the MOG2 background.
- `anomaly_test/`: images with road obstacles or unknown objects.
- `vehicle_test/`: images with normal sandbox vehicles, used to check false alarms.
- `output/`: generated debug images with anomaly boxes.

Photos are enough for offline tuning. Keep the camera angle as stable as
possible across folders.
