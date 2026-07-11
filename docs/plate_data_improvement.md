# 车牌识别数据增强与补数据流程

## 目标

车牌模块不要依赖固定车牌号纠错。提升准确率应依靠：

- 清洗车牌检测数据，去掉不符合真实场景的竖向旋转增强。
- 从沙盘照片中裁出车牌 crop，补充 OCR 的目标场景数据。
- 后续混入 CCPD/CLPD/CRPD 等开源数据集做通用能力补充。

## 1. 生成沙盘诊断报告

```powershell
python tools\debug_plate_batch.py --input-dir data\plate_debug --output-dir data\plate_debug_report
```

输出：

- `data/plate_debug_report/report.csv`
- `data/plate_debug_report/crops/`
- `data/plate_debug_report/annotated/`

## 2. 生成人工标签模板

```powershell
python tools\make_plate_labels_template.py --report data\plate_debug_report\report.csv --output data\plate_debug_labels.csv
```

只修改 `expected_plates` 列。多车牌用英文分号分隔：

```csv
image,expected_plates
example.jpg,京E4682Y;京K9134J
```

## 3. 评估真实准确率

确认 `data/plate_debug_labels.csv` 后运行：

```powershell
python tools\evaluate_plate_accuracy.py --report data\plate_debug_report\report.csv --labels data\plate_debug_labels.csv
```

输出指标：

- 图片级完全正确率
- 车牌级 precision / recall / F1
- 字符级准确率
- 错例：`data/plate_debug_report/evaluation_errors.csv`

## 4. 准备 OCR 沙盘 crop 数据

```powershell
python tools\prepare_sandbox_ocr_dataset.py --report data\plate_debug_report\report.csv --labels data\plate_debug_labels.csv --output-dir data\sandbox_plate_ocr
```

输出：

- `data/sandbox_plate_ocr/train/`
- `data/sandbox_plate_ocr/val/`
- `data/sandbox_plate_ocr/train.csv`
- `data/sandbox_plate_ocr/val.csv`

注意：训练前必须先人工确认 `data/plate_debug_labels.csv`。

## 5. 清洗 YOLO 车牌检测数据

```powershell
python tools\prepare_clean_plate_detection_dataset.py --source-root cloud\datasets\sandbox_plate --output-root data\sandbox_plate_detection_clean
```

默认会：

- 去掉 `rot90` / `rot270` 样本。
- 过滤宽高比小于 1 的竖向框。
- 过滤高度过小的框。

输出 YOLO 数据集：

- `data/sandbox_plate_detection_clean/data.yaml`

可用于后续 YOLO 训练。

## 6. 开源数据集接入建议

推荐组合：

- 检测：CCPD / CRPD + 沙盘整图。
- OCR：CCPD / CLPD 车牌 crop + 沙盘 crop。

建议比例：

- 通用系统：开源 70%，沙盘 30%。
- 沙盘演示系统：开源 30%-40%，沙盘 60%-70%。

不要使用 90/270 度旋转车牌增强；可使用轻微透视、亮度、模糊、压缩、噪声、正负 5-10 度小角度旋转。
