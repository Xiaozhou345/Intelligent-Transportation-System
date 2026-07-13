import os
import cv2
import numpy as np
import shutil
from pathlib import Path

CHARS = ['京', '沪', '津', '渝', '冀', '晋', '蒙', '辽', '吉', '黑',
         '苏', '浙', '皖', '闽', '赣', '鲁', '豫', '鄂', '湘', '粤',
         '桂', '琼', '川', '贵', '云', '藏', '陕', '甘', '青', '宁',
         '新',
         'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K',
         'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V',
         'W', 'X', 'Y', 'Z',
         '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
         '港', '澳', '警']

CHARS_DICT = {char: index for index, char in enumerate(CHARS)}

def decode_plate(chars_code):
    plate_text = ''
    for i in range(len(chars_code) // 2):
        code = int(chars_code[i*2:(i+1)*2])
        if code < len(CHARS):
            plate_text += CHARS[code]
        else:
            return None
    return plate_text

def parse_ccpd_filename(filename):
    basename = os.path.splitext(filename)[0]
    parts = basename.split('-')
    
    if len(parts) < 5:
        return None
    
    chars_code = parts[0]
    plate_text = decode_plate(chars_code)
    
    if plate_text is None:
        return None
    
    if not is_valid_plate(plate_text):
        return None
    
    if len(parts) >= 3:
        bbox_str = parts[2]
        try:
            coords = bbox_str.split('_')
            if len(coords) == 2:
                x1y1, x2y2 = coords
                x1, y1 = map(int, x1y1.split('&'))
                x2, y2 = map(int, x2y2.split('&'))
                bbox = (x1, y1, x2, y2)
            else:
                bbox = None
        except:
            bbox = None
    else:
        bbox = None
    
    corners = None
    if len(parts) >= 4:
        corner_str = parts[3]
        try:
            coords = corner_str.split('_')
            if len(coords) == 4:
                corners = []
                for c in coords:
                    x, y = map(int, c.split('&'))
                    corners.append((x, y))
        except:
            corners = None
    
    return plate_text, bbox, corners

def is_valid_plate(plate_text):
    if len(plate_text) < 7 or len(plate_text) > 8:
        return False
    
    for char in plate_text:
        if char not in CHARS_DICT:
            return False
    
    return True

def warp_plate(img, corners):
    if corners is None or len(corners) != 4:
        return img
    
    pts_src = np.array(corners, dtype=np.float32)
    
    dst_width = 94
    dst_height = 24
    pts_dst = np.array([[0, 0], [dst_width, 0], [dst_width, dst_height], [0, dst_height]], dtype=np.float32)
    
    try:
        M = cv2.getPerspectiveTransform(pts_src, pts_dst)
        warped = cv2.warpPerspective(img, M, (dst_width, dst_height))
        return warped
    except:
        return cv2.resize(img, (dst_width, dst_height))

def process_dataset(src_dir, dst_dir, train_ratio=0.85):
    img_extensions = ('.jpg', '.jpeg', '.png', '.bmp')
    
    all_files = []
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if f.lower().endswith(img_extensions) and not f.startswith('.'):
                all_files.append((root, f))
    
    print(f"Found {len(all_files)} images in source directory")
    
    np.random.seed(42)
    np.random.shuffle(all_files)
    
    train_count = int(len(all_files) * train_ratio)
    train_files = all_files[:train_count]
    val_files = all_files[train_count:]
    
    train_img_dir = os.path.join(dst_dir, 'train', 'images')
    train_label_dir = os.path.join(dst_dir, 'train', 'labels')
    val_img_dir = os.path.join(dst_dir, 'val', 'images')
    val_label_dir = os.path.join(dst_dir, 'val', 'labels')
    
    os.makedirs(train_img_dir, exist_ok=True)
    os.makedirs(train_label_dir, exist_ok=True)
    os.makedirs(val_img_dir, exist_ok=True)
    os.makedirs(val_label_dir, exist_ok=True)
    
    def process_files(file_list, img_dir, label_dir, split_name):
        count = 0
        skipped = 0
        
        for root, filename in file_list:
            src_path = os.path.join(root, filename)
            
            result = parse_ccpd_filename(filename)
            if result is None:
                skipped += 1
                continue
            
            plate_text, bbox, corners = result
            
            try:
                img = cv2.imread(src_path)
                if img is None:
                    skipped += 1
                    continue
                
                if bbox is not None:
                    x1, y1, x2, y2 = bbox
                    h, w = img.shape[:2]
                    x1 = max(0, x1)
                    y1 = max(0, y1)
                    x2 = min(w, x2)
                    y2 = min(h, y2)
                    
                    if x2 > x1 + 10 and y2 > y1 + 10:
                        plate_img = img[y1:y2, x1:x2]
                    else:
                        plate_img = img
                else:
                    plate_img = img
                
                if corners is not None:
                    warped = warp_plate(plate_img, corners)
                else:
                    warped = cv2.resize(plate_img, (94, 24))
                
                img_filename = f'ccpd_{count:07d}.jpg'
                label_filename = f'ccpd_{count:07d}.txt'
                
                cv2.imwrite(os.path.join(img_dir, img_filename), warped)
                
                with open(os.path.join(label_dir, label_filename), 'w', encoding='utf-8') as f:
                    f.write(plate_text)
                
                count += 1
                
                if count % 5000 == 0:
                    print(f"  {split_name}: processed {count} images")
            
            except Exception as e:
                skipped += 1
        
        return count, skipped
    
    print("Processing train set...")
    train_count, train_skipped = process_files(train_files, train_img_dir, train_label_dir, 'train')
    
    print("Processing val set...")
    val_count, val_skipped = process_files(val_files, val_img_dir, val_label_dir, 'val')
    
    with open(os.path.join(dst_dir, 'train.txt'), 'w', encoding='utf-8') as f:
        for i in range(train_count):
            f.write(f'train/images/ccpd_{i:07d}.jpg\n')
    
    with open(os.path.join(dst_dir, 'val.txt'), 'w', encoding='utf-8') as f:
        for i in range(val_count):
            f.write(f'val/images/ccpd_{i:07d}.jpg\n')
    
    print(f"\nProcessing complete!")
    print(f"Train set: {train_count} images ({train_skipped} skipped)")
    print(f"Val set: {val_count} images ({val_skipped} skipped)")
    print(f"Total: {train_count + val_count} images")
    print(f"Saved to: {dst_dir}")

if __name__ == '__main__':
    src_dir = r'F:\CCPD2019\CCPD2019'
    dst_dir = r'F:\CCPD2019\lpr94x24_subset'
    
    print(f"Source directory: {src_dir}")
    print(f"Destination directory: {dst_dir}")
    print(f"Processing CCPD2019 dataset...")
    
    process_dataset(src_dir, dst_dir, train_ratio=0.85)