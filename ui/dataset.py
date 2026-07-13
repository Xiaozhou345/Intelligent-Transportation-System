import os
import cv2
import numpy as np
import torch
from torch.utils.data import Dataset, ConcatDataset
from config import CHARS_DICT, IMAGE_WIDTH, IMAGE_HEIGHT, CLPD_CSV, CLPD_IMAGE_DIR, CCPD_ROOT, CCPD_TRAIN_DIR, CCPD_VAL_DIR


class CLPDDataset(Dataset):
    def __init__(self, split_file=None, transform=None):
        self.split_file = split_file
        self.transform = transform
        self.image_paths = []
        self.labels = []
        self._load_data()

    def _load_data(self):
        if self.split_file and os.path.exists(self.split_file):
            with open(self.split_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            for line in lines:
                line = line.strip()
                if line:
                    parts = line.split(',')
                    if len(parts) >= 2:
                        img_name = parts[0]
                        label = ','.join(parts[1:])
                        if img_name.startswith('CLPD_1200/'):
                            img_name = img_name[len('CLPD_1200/'):]
                        img_path = os.path.join(CLPD_IMAGE_DIR, img_name)
                        if os.path.exists(img_path):
                            self.image_paths.append(img_path)
                            self.labels.append(label)
        print(f"CLPD Loaded {len(self.image_paths)} images")

    def _parse_label(self, label_str):
        indices = []
        for c in label_str:
            if c in CHARS_DICT:
                indices.append(CHARS_DICT[c])
        return indices

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_path = self.image_paths[idx]
        label_str = self.labels[idx]
        label = self._parse_label(label_str)

        img = cv2.imread(img_path)
        if img is None:
            raise ValueError(f"Failed to read image: {img_path}")

        if img.shape[0] != IMAGE_HEIGHT or img.shape[1] != IMAGE_WIDTH:
            img = cv2.resize(img, (IMAGE_WIDTH, IMAGE_HEIGHT))
        
        img = img.astype(np.float32)
        img -= 127.5
        img *= 0.0078125
        img = np.transpose(img, (2, 0, 1))

        if self.transform:
            img = self.transform(img)

        label_length = len(label)
        label = np.array(label, dtype=np.int64)

        return torch.from_numpy(img), torch.from_numpy(label), label_length


class CCPDDataset(Dataset):
    def __init__(self, data_dir=None, list_file=None, transform=None):
        self.data_dir = data_dir
        self.list_file = list_file
        self.transform = transform
        self.image_paths = []
        self.labels = []
        self._load_data()

    def _load_data(self):
        if self.list_file and os.path.exists(self.list_file):
            with open(self.list_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            for line in lines:
                line = line.strip()
                if line:
                    img_rel_path = line.strip()
                    img_path = os.path.join(CCPD_ROOT, img_rel_path)
                    if os.path.exists(img_path):
                        txt_path = img_path.replace('images/', 'labels/').replace('.jpg', '.txt')
                        if os.path.exists(txt_path):
                            with open(txt_path, 'r', encoding='utf-8') as f:
                                label = f.read().strip()
                            self.image_paths.append(img_path)
                            self.labels.append(label)
        print(f"CCPD Loaded {len(self.image_paths)} images")

    def _parse_label(self, label_str):
        indices = []
        for c in label_str:
            if c in CHARS_DICT:
                indices.append(CHARS_DICT[c])
        return indices

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img_path = self.image_paths[idx]
        label_str = self.labels[idx]
        label = self._parse_label(label_str)

        img = cv2.imread(img_path)
        if img is None:
            raise ValueError(f"Failed to read image: {img_path}")

        if img.shape[0] != IMAGE_HEIGHT or img.shape[1] != IMAGE_WIDTH:
            img = cv2.resize(img, (IMAGE_WIDTH, IMAGE_HEIGHT))
        
        img = img.astype(np.float32)
        img -= 127.5
        img *= 0.0078125
        img = np.transpose(img, (2, 0, 1))

        if self.transform:
            img = self.transform(img)

        label_length = len(label)
        label = np.array(label, dtype=np.int64)

        return torch.from_numpy(img), torch.from_numpy(label), label_length


def get_mixed_dataset(train_split_file, val_split_file):
    clpd_train = CLPDDataset(split_file=train_split_file)
    clpd_val = CLPDDataset(split_file=val_split_file)

    ccpd_train = CCPDDataset(list_file=os.path.join(CCPD_ROOT, 'train.txt'))
    ccpd_val = CCPDDataset(list_file=os.path.join(CCPD_ROOT, 'val.txt'))

    train_dataset = ConcatDataset([ccpd_train, clpd_train])
    val_dataset = ConcatDataset([ccpd_val, clpd_val])

    return train_dataset, val_dataset


def collate_fn(batch):
    images = torch.stack([item[0] for item in batch])
    labels = [item[1] for item in batch]
    label_lengths = torch.tensor([item[2] for item in batch], dtype=torch.int64)

    max_len = max([len(l) for l in labels])
    padded_labels = torch.zeros(len(labels), max_len, dtype=torch.int64)
    for i, label in enumerate(labels):
        padded_labels[i, :len(label)] = label

    return images, padded_labels, label_lengths