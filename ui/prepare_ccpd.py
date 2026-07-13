import os
import cv2
import numpy as np
from tqdm import tqdm
import random

CCPD_ROOT = "F:/CCPD2019/CCPD2019"
OUT_ROOT = "F:/CCPD2019/lpr94x24"
TRAIN_RATIO = 0.9
LPR_W = 94
LPR_H = 24
random.seed(42)

province_map = {
    "0": "皖", "1": "沪", "2": "津", "3": "渝", "4": "冀",
    "5": "晋", "6": "蒙", "7": "辽", "8": "吉", "9": "黑",
    "10": "苏", "11": "浙", "12": "京", "13": "闽", "14": "赣",
    "15": "鲁", "16": "豫", "17": "鄂", "18": "湘", "19": "粤",
    "20": "桂", "21": "琼", "22": "川", "23": "贵", "24": "云",
    "25": "藏", "26": "陕", "27": "甘", "28": "青", "29": "宁", "30": "新"
}
char_table = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def mkdir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def parse_ccpd_name(filename):
    stem = filename.split(".")[0]
    parts = stem.split("-")
    four_pt_str = parts[3]
    pt_list = []
    for coord in four_pt_str.split("_"):
        x, y = coord.split("&")
        pt_list.append([int(x), int(y)])
    pts = np.array(pt_list, dtype=np.float32)
    code_seq = parts[4].split("_")
    plate = [province_map[code_seq[0]]]
    for c in code_seq[1:]:
        idx = int(c)
        plate.append(char_table[idx])
    plate_text = "".join(plate)
    return plate_text, pts


def warp_plate(img, src_pts, target_w, target_h):
    dst_pts = np.array([
        [0, 0],
        [target_w - 1, 0],
        [target_w - 1, target_h - 1],
        [0, target_h - 1]
    ], dtype=np.float32)
    trans_mat = cv2.getPerspectiveTransform(src_pts, dst_pts)
    plate_crop = cv2.warpPerspective(img, trans_mat, (target_w, target_h))
    return plate_crop


if __name__ == "__main__":
    train_img_dir = os.path.join(OUT_ROOT, "train/images")
    train_label_dir = os.path.join(OUT_ROOT, "train/labels")
    val_img_dir = os.path.join(OUT_ROOT, "val/images")
    val_label_dir = os.path.join(OUT_ROOT, "val/labels")
    mkdir(train_img_dir)
    mkdir(train_label_dir)
    mkdir(val_img_dir)
    mkdir(val_label_dir)

    all_img_paths = []
    sub_dirs = [d for d in os.listdir(CCPD_ROOT) if os.path.isdir(os.path.join(CCPD_ROOT, d)) and d != "ccpd_np"]
    for sub in sub_dirs:
        sub_path = os.path.join(CCPD_ROOT, sub)
        img_names = [f for f in os.listdir(sub_path) if f.endswith(".jpg")]
        for name in img_names:
            all_img_paths.append(os.path.join(sub_path, name))
    random.shuffle(all_img_paths)
    split_idx = int(len(all_img_paths) * TRAIN_RATIO)
    train_paths = all_img_paths[:split_idx]
    val_paths = all_img_paths[split_idx:]

    def process_batch(img_list, img_out_dir, label_out_dir, split_name):
        print(f"\n开始处理 {split_name} 集，共 {len(img_list)} 张")
        for idx, img_path in enumerate(tqdm(img_list)):
            img = cv2.imread(img_path)
            if img is None:
                continue
            fname = os.path.basename(img_path)
            plate_text, pts = parse_ccpd_name(fname)
            crop_plate = warp_plate(img, pts, LPR_W, LPR_H)
            save_name = f"ccpd_{idx:07d}.jpg"
            save_img_path = os.path.join(img_out_dir, save_name)
            cv2.imwrite(save_img_path, crop_plate)
            txt_path = os.path.join(label_out_dir, save_name.replace(".jpg", ".txt"))
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(plate_text)
        print(f"{split_name} 集处理完成")

    process_batch(train_paths, train_img_dir, train_label_dir, "train")
    process_batch(val_paths, val_img_dir, val_label_dir, "val")

    train_txt = os.path.join(OUT_ROOT, "train.txt")
    val_txt = os.path.join(OUT_ROOT, "val.txt")
    with open(train_txt, "w", encoding="utf-8") as f:
        for img_name in sorted(os.listdir(train_img_dir)):
            f.write(f"train/images/{img_name}\n")
    with open(val_txt, "w", encoding="utf-8") as f:
        for img_name in sorted(os.listdir(val_img_dir)):
            f.write(f"val/images/{img_name}\n")

    print(f"\n数据集生成完成！输出根目录：{OUT_ROOT}")
    print(f"训练集图片路径：{train_img_dir}")
    print(f"验证集图片路径：{val_img_dir}")
    print(f"训练列表：{train_txt}  验证列表：{val_txt}")