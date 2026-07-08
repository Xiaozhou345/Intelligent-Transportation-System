# Sandbox Drivable Area Dataset

This dataset is used to train a segmentation model for sandbox road/drivable
area detection.

## Class

- `drivable_area`: road surface where sandbox vehicles can actually drive.

Do not label poles, trees, railings, decorations, buildings, sidewalks, or road
areas visually blocked by fixed structures.

## Structure

The Roboflow export from `D:\大二下小学期\sandbox_drivable.v1i.yolov8` has been
migrated into this repository:

```text
data/sandbox_drivable/
├── images/
│   ├── train/
│   └── val/
├── labels/
│   ├── train/
│   └── val/
└── data.yaml
```

Export labels in YOLO segmentation format.

Current split:

- train: 40 images, 40 labels
- val: 10 images, 10 labels

## Train

From the repository root:

```powershell
python cloud\ai_models\anomaly_detection\train_drivable_segmenter.py --data data\sandbox_drivable\data.yaml --model yolo11n-seg.pt --epochs 80 --imgsz 640 --batch 4
```

After training, copy the best weight to:

```text
cloud/ai_models/anomaly_detection/sandbox_drivable_best.pt
```

The anomaly processor can then load it only for the road-anomaly scene:

```python
RoadAnomalyProcessor(
    drivable_model_path="cloud/ai_models/anomaly_detection/sandbox_drivable_best.pt"
)
```
