import os
import random

CCPD_IMG_DIR = "F:/CCPD2019/lpr94x24/train/images"
CCPD_LABEL_DIR = "F:/CCPD2019/lpr94x24/train/labels"
OUT_ROOT = "F:/CCPD2019/lpr94x24_subset"
TRAIN_SIZE = 10000
VAL_SIZE = 1000
SEED = 42

random.seed(SEED)


def mkdir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def main():
    img_names = [f for f in os.listdir(CCPD_IMG_DIR) if f.endswith(".jpg")]
    random.shuffle(img_names)

    train_names = img_names[:TRAIN_SIZE]
    val_names = img_names[TRAIN_SIZE:TRAIN_SIZE + VAL_SIZE]

    train_img_out = os.path.join(OUT_ROOT, "train/images")
    train_label_out = os.path.join(OUT_ROOT, "train/labels")
    val_img_out = os.path.join(OUT_ROOT, "val/images")
    val_label_out = os.path.join(OUT_ROOT, "val/labels")

    mkdir(train_img_out)
    mkdir(train_label_out)
    mkdir(val_img_out)
    mkdir(val_label_out)

    import shutil

    for name in train_names:
        src_img = os.path.join(CCPD_IMG_DIR, name)
        src_label = os.path.join(CCPD_LABEL_DIR, name.replace(".jpg", ".txt"))
        dst_img = os.path.join(train_img_out, name)
        dst_label = os.path.join(train_label_out, name.replace(".jpg", ".txt"))
        shutil.copy(src_img, dst_img)
        if os.path.exists(src_label):
            shutil.copy(src_label, dst_label)

    for name in val_names:
        src_img = os.path.join(CCPD_IMG_DIR, name)
        src_label = os.path.join(CCPD_LABEL_DIR, name.replace(".jpg", ".txt"))
        dst_img = os.path.join(val_img_out, name)
        dst_label = os.path.join(val_label_out, name.replace(".jpg", ".txt"))
        shutil.copy(src_img, dst_img)
        if os.path.exists(src_label):
            shutil.copy(src_label, dst_label)

    train_txt = os.path.join(OUT_ROOT, "train.txt")
    val_txt = os.path.join(OUT_ROOT, "val.txt")

    with open(train_txt, "w", encoding="utf-8") as f:
        for name in sorted(os.listdir(train_img_out)):
            f.write(f"train/images/{name}\n")

    with open(val_txt, "w", encoding="utf-8") as f:
        for name in sorted(os.listdir(val_img_out)):
            f.write(f"val/images/{name}\n")

    print(f"子集生成完成！")
    print(f"训练集: {len(os.listdir(train_img_out))} 张")
    print(f"验证集: {len(os.listdir(val_img_out))} 张")
    print(f"输出目录: {OUT_ROOT}")


if __name__ == "__main__":
    main()