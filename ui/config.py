import os

CHARS = ['京', '沪', '津', '渝', '冀', '晋', '蒙', '辽', '吉', '黑',
         '苏', '浙', '皖', '闽', '赣', '鲁', '豫', '鄂', '湘', '粤',
         '桂', '琼', '川', '贵', '云', '藏', '陕', '甘', '青', '宁',
         '新',
         '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
         'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K',
         'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V',
         'W', 'X', 'Y', 'Z', 'I', 'O', '-'
         ]

CHARS_DICT = {char: index for index, char in enumerate(CHARS)}
NUM_CLASSES = len(CHARS)

IMAGE_WIDTH = 94
IMAGE_HEIGHT = 24
IMAGE_CHANNELS = 3

BATCH_SIZE = 32
EPOCHS = 25
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4

CLPD_ROOT = 'F:/CLPD/CLPD'
CLPD_CSV = os.path.join(CLPD_ROOT, 'CLPD.csv')
CLPD_IMAGE_DIR = os.path.join(CLPD_ROOT, 'CLPD_1200')

CCPD_ROOT = 'F:/CCPD2019/lpr94x24_subset'
CCPD_TRAIN_DIR = os.path.join(CCPD_ROOT, 'train')
CCPD_VAL_DIR = os.path.join(CCPD_ROOT, 'val')
CCPD_TRAIN_LIST = os.path.join(CCPD_ROOT, 'train.txt')
CCPD_VAL_LIST = os.path.join(CCPD_ROOT, 'val.txt')

TRAIN_DATA_DIR = 'data/CLPD_dataset/train'
TEST_DATA_DIR = 'data/CLPD_dataset/test'
VALID_DATA_DIR = 'data/CLPD_dataset/val'

USE_MIXED_DATA = True

MODEL_SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models')
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')

os.makedirs(MODEL_SAVE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

PRETRAINED_PATH = os.path.join(MODEL_SAVE_DIR, 'pretrained_lprnet.pth')