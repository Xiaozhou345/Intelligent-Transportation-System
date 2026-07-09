import os
import torch
import cv2
import numpy as np
import random
from model import build_lprnet
from config import CHARS, NUM_CLASSES, IMAGE_WIDTH, IMAGE_HEIGHT, MODEL_SAVE_DIR


def decode(preds):
    preds = preds.softmax(dim=-1)
    preds = preds.argmax(dim=-1)
    preds = preds.cpu().numpy()

    result = []
    for pred in preds:
        plate = ''
        prev_char = -1
        for char in pred:
            if char != NUM_CLASSES - 1 and char != prev_char:
                plate += CHARS[char]
                prev_char = char
        result.append(plate)
    return result


def test_on_lprnet_dataset(test_dir, num_samples=50):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")

    model = build_lprnet().to(device)
    
    model_path = os.path.join(MODEL_SAVE_DIR, 'lprnet_best.pth')
    if not os.path.exists(model_path):
        model_path = os.path.join(MODEL_SAVE_DIR, 'lprnet_final.pth')
    if not os.path.exists(model_path):
        model_path = os.path.join(MODEL_SAVE_DIR, 'pretrained_lprnet.pth')
    
    if not os.path.exists(model_path):
        print(f"Error: Model file not found at {model_path}")
        return

    checkpoint = torch.load(model_path, map_location=device)
    if 'model_state_dict' in checkpoint:
        model.load_state_dict(checkpoint['model_state_dict'])
        print(f"Loaded model from {model_path}")
        if 'accuracy' in checkpoint:
            print(f"Best validation accuracy: {checkpoint['accuracy']:.4f}")
    else:
        model.load_state_dict(checkpoint, strict=False)
        print(f"Loaded model directly from {model_path} (strict=False)")

    model.eval()

    all_img_files = [f for f in os.listdir(test_dir) if f.endswith('.jpg')]
    if num_samples > len(all_img_files):
        num_samples = len(all_img_files)
        print(f"Warning: Only {len(all_img_files)} images available, testing all of them")
    
    test_files = random.sample(all_img_files, num_samples)
    print(f"\nTesting {len(test_files)} images from {test_dir}")

    correct = 0
    total = 0
    wrong_cases = []

    with torch.no_grad():
        for img_file in test_files:
            img_path = os.path.join(test_dir, img_file)
            true_plate = os.path.splitext(img_file)[0]
            
            img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                print(f"Warning: Failed to read {img_file}")
                continue

            if img.shape[0] != IMAGE_HEIGHT or img.shape[1] != IMAGE_WIDTH:
                img = cv2.resize(img, (IMAGE_WIDTH, IMAGE_HEIGHT))
            
            img = img.astype(np.float32)
            img -= 127.5
            img *= 0.0078125
            img = np.transpose(img, (2, 0, 1))
            img = torch.from_numpy(img).unsqueeze(0).to(device)

            preds = model(img)
            decoded_preds = decode(preds)
            pred_plate = decoded_preds[0]

            total += 1
            if pred_plate == true_plate:
                correct += 1
            else:
                wrong_cases.append((true_plate, pred_plate))

    accuracy = correct / total if total > 0 else 0
    print(f"\n{'='*60}")
    print(f"Test Results on LPRNet_Pytorch test dataset:")
    print(f"{'='*60}")
    print(f"Total samples: {total}")
    print(f"Correct predictions: {correct}")
    print(f"Accuracy: {accuracy:.4f}")
    print(f"Error rate: {(1 - accuracy):.4f}")

    if wrong_cases:
        print(f"\nWrong predictions ({len(wrong_cases)}):")
        print(f"{'真实车牌':<12} {'预测结果':<12}")
        print(f"{'----------':<12} {'----------':<12}")
        for true, pred in wrong_cases:
            print(f"{true:<12} {pred:<12}")

    return accuracy


if __name__ == '__main__':
    test_dir = r'C:\Users\Asus\Desktop\LPRNet_Pytorch\data\test'
    test_on_lprnet_dataset(test_dir, num_samples=50)