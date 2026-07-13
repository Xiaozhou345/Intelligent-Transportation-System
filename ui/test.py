import os
import torch
import cv2
import numpy as np
from torch.utils.data import DataLoader
from model import build_lprnet
from dataset import PlateDataset, collate_fn
from config import (
    CHARS, CHARS_DICT, NUM_CLASSES,
    BATCH_SIZE, CLPD_ROOT, MODEL_SAVE_DIR,
    IMAGE_WIDTH, IMAGE_HEIGHT
)

TEST_SPLIT = os.path.join(CLPD_ROOT, 'splits', 'test.txt')


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


def test_model():
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")

    model = build_lprnet().to(device)
    
    model_path = os.path.join(MODEL_SAVE_DIR, 'lprnet_best.pth')
    if not os.path.exists(model_path):
        model_path = os.path.join(MODEL_SAVE_DIR, 'lprnet_final.pth')
    
    if not os.path.exists(model_path):
        print(f"Error: Model file not found at {model_path}")
        return

    checkpoint = torch.load(model_path, map_location=device)
    model.load_state_dict(checkpoint['model_state_dict'])
    print(f"Loaded model from {model_path}")
    if 'accuracy' in checkpoint:
        print(f"Best validation accuracy: {checkpoint['accuracy']:.4f}")

    test_dataset = PlateDataset(split_file=TEST_SPLIT)
    test_loader = DataLoader(test_dataset, batch_size=BATCH_SIZE, shuffle=False, 
                             collate_fn=collate_fn, num_workers=4)

    model.eval()
    
    correct = 0
    total = 0
    all_preds = []
    all_labels = []

    with torch.no_grad():
        for images, labels, label_lengths in test_loader:
            images = images.to(device)
            labels = labels.to(device)
            label_lengths = label_lengths.to(device)

            preds = model(images)
            decoded_preds = decode(preds)

            for i in range(len(decoded_preds)):
                true_label = ''.join([CHARS[int(c)] for c in labels[i][:label_lengths[i]]])
                all_preds.append(decoded_preds[i])
                all_labels.append(true_label)
                
                if decoded_preds[i] == true_label:
                    correct += 1
                total += 1

    accuracy = correct / total if total > 0 else 0
    print(f"\nTest Results:")
    print(f"Total samples: {total}")
    print(f"Correct predictions: {correct}")
    print(f"Accuracy: {accuracy:.4f}")
    print(f"Error rate: {(1 - accuracy):.4f}")

    print("\nSample predictions:")
    for i in range(min(20, len(all_preds))):
        status = "✓" if all_preds[i] == all_labels[i] else "✗"
        print(f"  {status} {all_labels[i]} -> {all_preds[i]}")


def predict_single_image(image_path, model_path=None):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    model = build_lprnet().to(device)
    
    if model_path is None:
        model_path = os.path.join(MODEL_SAVE_DIR, 'lprnet_best.pth')
        if not os.path.exists(model_path):
            model_path = os.path.join(MODEL_SAVE_DIR, 'lprnet_final.pth')

    checkpoint = torch.load(model_path, map_location=device)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()

    img = cv2.imread(image_path)
    if img is None:
        print(f"Error: Failed to read image {image_path}")
        return None

    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (IMAGE_WIDTH, IMAGE_HEIGHT))
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))
    img = torch.from_numpy(img).unsqueeze(0).to(device)

    with torch.no_grad():
        preds = model(img)
        decoded = decode(preds)
    
    return decoded[0]


if __name__ == '__main__':
    test_model()