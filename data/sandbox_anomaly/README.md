# Sandbox Anomaly Dataset

This local folder is for tuning the road anomaly detector. Image/video data is
ignored by Git and should not be committed.

## Folders

- `clean_road/`: normal road frames used to initialize the MOG2 background.
- `anomaly_test/`: images with road obstacles or unknown objects.
- `vehicle_test/`: images with normal sandbox vehicles, used to check false alarms.
- `output/`: generated debug images with anomaly boxes.

For MOG2 tuning, `clean_road/` and test images should come from the same fixed
camera position. If the camera angle changes between folders, MOG2 will treat
large parts of the image as foreground, which is expected and not useful for
threshold tuning.
