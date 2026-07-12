"""
车牌识别模块
使用LPRNet进行中国车牌字符识别
"""
import os
import torch
import torch.nn as nn
import cv2
import numpy as np


# LPRNet字符集（支持中国车牌）
CHARS = ['京', '沪', '津', '渝', '冀', '晋', '蒙', '辽', '吉', '黑',
         '苏', '浙', '皖', '闽', '赣', '鲁', '豫', '鄂', '湘', '粤',
         '桂', '琼', '川', '贵', '云', '藏', '陕', '甘', '青', '宁',
         '新',
         '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
         'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K',
         'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'T', 'U', 'V',
         'W', 'X', 'Y', 'Z', 'I', 'O', '-'
         ]

CHARS_DICT = {char: i for i, char in enumerate(CHARS)}
BLANK_INDEX = len(CHARS) - 1
PROVINCE_CHARS = set(CHARS[:31])
LETTER_CHARS = set("ABCDEFGHJKLMNPQRSTUVWXYZ")
PLATE_TAIL_CHARS = set("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789")


def crop_plate_image(frame, bbox, pad_ratio=0.0):
    """Crop a plate bbox with optional margin and clipped image bounds."""
    if frame is None or frame.size == 0:
        return None

    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    bw = max(0, x2 - x1)
    bh = max(0, y2 - y1)
    if bw == 0 or bh == 0:
        return None

    pad_x = max(2, int(round(bw * pad_ratio))) if pad_ratio > 0 else 0
    pad_y = max(2, int(round(bh * pad_ratio))) if pad_ratio > 0 else 0
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x2 + pad_x)
    y2 = min(h, y2 + pad_y)

    if x2 <= x1 or y2 <= y1:
        return None
    return frame[y1:y2, x1:x2]


def refine_plate_crop_by_blue_region(plate_img):
    """Tighten a blue plate crop using its blue background when available."""
    if plate_img is None or plate_img.size == 0:
        return None

    hsv = cv2.cvtColor(plate_img, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([90, 40, 30])
    upper_blue = np.array([135, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(contour)
    image_area = plate_img.shape[0] * plate_img.shape[1]
    if image_area <= 0 or area / image_area < 0.15:
        return None

    x, y, w, h = cv2.boundingRect(contour)
    if w < 20 or h < 8:
        return None

    pad = 2
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(plate_img.shape[1], x + w + pad)
    y2 = min(plate_img.shape[0], y + h + pad)
    if x2 <= x1 or y2 <= y1:
        return None
    return plate_img[y1:y2, x1:x2]


def normalize_plate_number(plate_number):
    """Normalize OCR text before validation and cache matching."""
    if not plate_number:
        return ""
    return str(plate_number).strip().replace("-", "").replace(" ", "").upper()


def is_valid_plate_number(plate_number):
    """Validate common mainland China fuel/new-energy plate formats."""
    plate_number = normalize_plate_number(plate_number)
    if len(plate_number) not in (7, 8):
        return False
    if plate_number[0] not in PROVINCE_CHARS:
        return False
    if plate_number[1] not in LETTER_CHARS:
        return False
    return all(char in PLATE_TAIL_CHARS for char in plate_number[2:])


def is_ocr_candidate_crop(plate_img, min_height=30, min_aspect=1.0):
    """Reject tiny or vertical crops before OCR to reduce obvious false reads."""
    if plate_img is None or plate_img.size == 0:
        return False
    h, w = plate_img.shape[:2]
    if h < min_height:
        return False
    return (w / max(h, 1)) >= min_aspect


class small_basic_block(nn.Module):
    def __init__(self, ch_in, ch_out):
        super(small_basic_block, self).__init__()
        self.block = nn.Sequential(
            nn.Conv2d(ch_in, ch_out // 4, kernel_size=1),
            nn.ReLU(),
            nn.Conv2d(ch_out // 4, ch_out // 4, kernel_size=(3, 1), padding=(1, 0)),
            nn.ReLU(),
            nn.Conv2d(ch_out // 4, ch_out // 4, kernel_size=(1, 3), padding=(0, 1)),
            nn.ReLU(),
            nn.Conv2d(ch_out // 4, ch_out, kernel_size=1),
        )

    def forward(self, x):
        return self.block(x)


class LPRNet(nn.Module):
    def __init__(self, lpr_max_len, phase, class_num, dropout_rate):
        super(LPRNet, self).__init__()
        self.phase = phase
        self.lpr_max_len = lpr_max_len
        self.class_num = class_num
        self.backbone = nn.Sequential(
            nn.Conv2d(in_channels=3, out_channels=64, kernel_size=3, stride=1),
            nn.BatchNorm2d(num_features=64),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(1, 1, 1)),
            small_basic_block(ch_in=64, ch_out=128),
            nn.BatchNorm2d(num_features=128),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(2, 1, 2)),
            small_basic_block(ch_in=64, ch_out=256),
            nn.BatchNorm2d(num_features=256),
            nn.ReLU(),
            small_basic_block(ch_in=256, ch_out=256),
            nn.BatchNorm2d(num_features=256),
            nn.ReLU(),
            nn.MaxPool3d(kernel_size=(1, 3, 3), stride=(4, 1, 2)),
            nn.Dropout(dropout_rate),
            nn.Conv2d(in_channels=64, out_channels=256, kernel_size=(1, 4), stride=1),
            nn.BatchNorm2d(num_features=256),
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Conv2d(in_channels=256, out_channels=class_num, kernel_size=(13, 1), stride=1),
            nn.BatchNorm2d(num_features=class_num),
            nn.ReLU(),
        )
        self.container = nn.Sequential(
            nn.Conv2d(in_channels=448 + self.class_num, out_channels=self.class_num,
                      kernel_size=(1, 1), stride=(1, 1)),
        )

    def forward(self, x):
        keep_features = list()
        for i, layer in enumerate(self.backbone.children()):
            x = layer(x)
            if i in [2, 6, 13, 22]:
                keep_features.append(x)

        global_context = list()
        for i, f in enumerate(keep_features):
            if i in [0, 1]:
                f = nn.AvgPool2d(kernel_size=5, stride=5)(f)
            if i in [2]:
                f = nn.AvgPool2d(kernel_size=(4, 10), stride=(4, 2))(f)
            f_pow = torch.pow(f, 2)
            f_mean = torch.mean(f_pow)
            f = torch.div(f, f_mean)
            global_context.append(f)

        x = torch.cat(global_context, 1)
        x = self.container(x)
        logits = torch.mean(x, dim=2)

        return logits


class PlateRecognizer:
    """车牌识别器"""

    def __init__(self, model_path='Final_LPRNet_model.pth'):
        """
        初始化车牌识别器

        Args:
            model_path: LPRNet模型权重路径
        """
        print(f"正在加载LPRNet模型: {model_path}")

        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        self.lpr_max_len = 8
        self.img_size = (94, 24)  # width, height

        # 构建模型
        self.model = LPRNet(
            lpr_max_len=self.lpr_max_len,
            phase=False,
            class_num=len(CHARS),
            dropout_rate=0
        )

        # 加载权重
        self.model.to(self.device)
        state_dict = self._load_compatible_state_dict(model_path)
        self.model.load_state_dict(state_dict, strict=True)
        self.model.eval()

        print("车牌识别器初始化完成")
        if os.getenv('ITS_WARMUP_MODELS', 'true').lower() == 'true':
            self._warmup()

    def _warmup(self):
        """Initialize LPRNet kernels before the first recognized plate."""
        try:
            dummy = torch.zeros((1, 3, self.img_size[1], self.img_size[0]), device=self.device)
            with torch.no_grad():
                self.model(dummy)
            if self.device.type == 'cuda':
                torch.cuda.synchronize()
            print("车牌识别器预热完成")
        except Exception as exc:
            print(f"车牌识别器预热失败，将在首次识别时重试: {exc}")

    def _load_compatible_state_dict(self, model_path):
        """兼容纯 state_dict 与包含 model_state_dict 的 checkpoint。"""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"LPRNet 模型不存在: {model_path}")

        checkpoint = torch.load(model_path, map_location=self.device)

        # 训练脚本保存格式：{'model_state_dict': ..., ...}
        if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
            state_dict = checkpoint['model_state_dict']
        else:
            state_dict = checkpoint

        # 新训练脚本模型结构与当前 cloud 运行结构不同，不能直接复用
        sample_keys = list(state_dict.keys())[:5]
        if sample_keys and any(key.startswith('stage') for key in sample_keys):
            raise ValueError(
                "当前 checkpoint 来自新的 UI LPRNet 训练结构（stage*），"
                "与 cloud 运行时 LPRNet 结构不兼容，请优先使用 Final_LPRNet_model.pth "
                "或 ui/models/pretrained_lprnet.pth。"
            )

        return state_dict

    def preprocess(self, plate_img):
        """
        预处理车牌图像

        Args:
            plate_img: 车牌区域图像 (numpy array)

        Returns:
            torch.Tensor: 预处理后的tensor
        """
        if plate_img is None or plate_img.size == 0:
            raise ValueError("空车牌图像，无法识别")

        # 调整大小到94x24
        img = cv2.resize(plate_img, self.img_size)

        # 转换为float并归一化（与 cloud 原始推理 & 新 dataset 预处理保持一致）
        img = img.astype('float32')
        img -= 127.5
        img *= 0.0078125

        # 转换为CHW格式
        img = np.transpose(img, (2, 0, 1))

        # 转换为tensor
        img_tensor = torch.from_numpy(img).float()
        img_tensor = img_tensor.unsqueeze(0)  # 添加batch维度

        return img_tensor

    def decode(self, logits):
        """
        解码模型输出为车牌号

        Args:
            logits: 模型输出logits

        Returns:
            str: 车牌号字符串
        """
        # CTC greedy decode: remove blanks and collapse repeated chars.
        logits = logits.cpu().detach().numpy()
        pred = np.argmax(logits, axis=1)[0]

        plate_chars = []
        pre_c = BLANK_INDEX
        for c in pred:
            if c != pre_c and c != BLANK_INDEX:
                plate_chars.append(CHARS[c])
            pre_c = c

        return ''.join(plate_chars)

    def recognize(self, plate_img):
        """
        识别车牌号

        Args:
            plate_img: 车牌区域图像 (numpy array, BGR格式)

        Returns:
            str: 识别的车牌号
        """
        # 预处理
        img_tensor = self.preprocess(plate_img)
        img_tensor = img_tensor.to(self.device)

        # 推理
        with torch.no_grad():
            logits = self.model(img_tensor)

        # 解码
        plate_number = self.decode(logits)

        return plate_number

    def recognize_best(self, plate_img):
        """Recognize with a conservative blue-region retry for blue plates."""
        plate_number = normalize_plate_number(self.recognize(plate_img))
        if is_valid_plate_number(plate_number):
            return plate_number

        refined_img = refine_plate_crop_by_blue_region(plate_img)
        if refined_img is None:
            return plate_number

        refined_number = normalize_plate_number(self.recognize(refined_img))
        if is_valid_plate_number(refined_number):
            return refined_number
        return plate_number


if __name__ == '__main__':
    # 测试代码
    recognizer = PlateRecognizer()

    # 创建测试图像（随机）
    test_img = np.random.randint(0, 255, (100, 300, 3), dtype=np.uint8)

    result = recognizer.recognize(test_img)
    print(f"\n识别结果: {result}")
    print("车牌识别器测试完成")
