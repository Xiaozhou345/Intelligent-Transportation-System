import os
import torch
import cv2
import numpy as np
import random
import sys

sys.path.insert(0, r'C:\Users\Asus\Desktop\LPRNet_Pytorch')

from model.LPRNet import build_lprnet
from data.load_data import CHARS


def decode(preds):
    preds = preds.cpu().detach().numpy()
    result = []
    for i in range(preds.shape[0]):
        preb = preds[i, :, :]
        preb_label = []
        for j in range(preb.shape[1]):
            preb_label.append(np.argmax(preb[:, j], axis=0))
        no_repeat_blank_label = []
        pre_c = preb_label[0]
        if pre_c != len(CHARS) - 1:
            no_repeat_blank_label.append(pre_c)
        for c in preb_label:
            if (pre_c == c) or (c == len(CHARS) - 1):
                if c == len(CHARS) - 1:
                    pre_c = c
                continue
            no_repeat_blank_label.append(c)
            pre_c = c
        plate = ''.join([CHARS[idx] for idx in no_repeat_blank_label])
        result.append(plate)
    return result


def test_on_lprnet_dataset(test_dir, num_samples=50):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")

    model = build_lprnet(lpr_max_len=8, phase=False, class_num=len(CHARS), dropout_rate=0).to(device)
    
    model_path = r'C:\Users\Asus\Desktop\LPRNet_Pytorch\weights\Final_LPRNet_model.pth'
    if not os.path.exists(model_path):
        print(f"Error: Model file not found at {model_path}")
        return

    checkpoint = torch.load(model_path, map_location=device)
    model.load_state_dict(checkpoint)
    print(f"Loaded model from {model_path}")

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

            if img.shape[0] != 24 or img.shape[1] != 94:
                img = cv2.resize(img, (94, 24))
            
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