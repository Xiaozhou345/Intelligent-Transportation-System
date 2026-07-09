import argparse
import sys
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cloud.ai_models.plate_detection.detector import PlateDetector
from cloud.ai_models.plate_recognition.plate_recognizer import PlateRecognizer


def main():
    parser = argparse.ArgumentParser(description="单张图片车牌检测 + LPRNet OCR 测试脚本")
    parser.add_argument("image_path", help="待测试图片路径")
    parser.add_argument(
        "--plate-model",
        default="cloud/ai_models/plate_detection/sandbox_plate_best.pt",
        help="车牌检测YOLO模型路径",
    )
    parser.add_argument(
        "--lpr-model",
        default="cloud/ai_models/plate_recognition/Final_LPRNet_model.pth",
        help="LPRNet模型路径",
    )
    parser.add_argument("--conf", type=float, default=0.20, help="车牌检测置信度阈值")
    parser.add_argument(
        "--output-dir",
        default="plate_test_output",
        help="车牌裁剪输出目录",
    )
    args = parser.parse_args()

    image_path = Path(args.image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"图片读取失败: {image_path}")

    print(f"测试图片: {image_path}")
    print(f"图片尺寸: {img.shape[1]}x{img.shape[0]}")

    plate_detector = PlateDetector(model_path=args.plate_model, conf_threshold=args.conf)
    plate_recognizer = PlateRecognizer(model_path=args.lpr_model)

    plates = plate_detector.detect(img)
    print(f"\n检测到车牌数量: {len(plates)}")

    if not plates:
        print("没有检测到车牌")
        return

    for i, plate in enumerate(plates, 1):
        x1, y1, x2, y2 = plate['bbox']
        crop = img[y1:y2, x1:x2]

        if crop is None or crop.size == 0:
            print(f"\n车牌 #{i} 裁剪为空，跳过")
            continue

        try:
            text = plate_recognizer.recognize(crop)
        except Exception as e:
            text = f"OCR失败: {e}"

        print(f"\n车牌 #{i}")
        print(f"  bbox: {plate['bbox']}")
        print(f"  confidence: {plate['confidence']:.3f}")
        print(f"  OCR结果: {text}")

        crop_path = output_dir / f"{image_path.stem}_plate_{i}.jpg"
        cv2.imwrite(str(crop_path), crop)
        print(f"  裁剪图已保存: {crop_path}")


if __name__ == "__main__":
    main()
