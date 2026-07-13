import os
import sys
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from model import build_lprnet
from dataset import CLPDDataset, CCPDDataset, collate_fn, get_mixed_dataset
from config import (
    CHARS, CHARS_DICT, NUM_CLASSES,
    BATCH_SIZE, EPOCHS, LEARNING_RATE, WEIGHT_DECAY,
    CLPD_ROOT, CCPD_ROOT, MODEL_SAVE_DIR, LOG_DIR,
    USE_MIXED_DATA, PRETRAINED_PATH
)

TRAIN_SPLIT = os.path.join(CLPD_ROOT, 'splits', 'train.txt')
VALID_SPLIT = os.path.join(CLPD_ROOT, 'splits', 'val.txt')
TEST_SPLIT = os.path.join(CLPD_ROOT, 'splits', 'test.txt')

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)
sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', buffering=1)


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


def calculate_accuracy(preds, labels, label_lengths):
    decoded_preds = decode(preds)
    correct = 0
    total = len(labels)

    for i in range(total):
        true_label = ''.join([CHARS[int(c)] for c in labels[i][:label_lengths[i]]])
        if decoded_preds[i] == true_label:
            correct += 1

    return correct / total if total > 0 else 0


def train_epoch(model, data_loader, criterion, optimizer, device, writer, global_step, is_train=True):
    if is_train:
        model.train()
    else:
        model.eval()

    total_loss = 0.0
    total_acc = 0.0
    total_count = 0

    with torch.set_grad_enabled(is_train):
        for images, labels, label_lengths in data_loader:
            images = images.to(device)
            labels = labels.to(device)
            label_lengths = label_lengths.to(device)

            if is_train:
                optimizer.zero_grad()

            preds = model(images)
            log_probs = preds.log_softmax(dim=-1).permute(2, 0, 1)
            pred_lengths = torch.full((preds.size(0),), preds.size(2), dtype=torch.int64).to(device)

            flat_labels = []
            for i in range(labels.size(0)):
                flat_labels.extend(labels[i, :label_lengths[i]].tolist())
            flat_labels = torch.tensor(flat_labels, dtype=torch.int64).to(device)

            loss = criterion(log_probs, flat_labels, pred_lengths, label_lengths)

            if is_train:
                loss.backward()
                optimizer.step()

            total_loss += loss.item() * images.size(0)
            total_acc += calculate_accuracy(preds, labels.cpu(), label_lengths.cpu()) * images.size(0)
            total_count += images.size(0)
            if is_train:
                global_step += 1
                if global_step % 10 == 0:
                    writer.add_scalar('Train/Loss', loss.item(), global_step)

    avg_loss = total_loss / total_count
    avg_acc = total_acc / total_count

    return avg_loss, avg_acc, global_step


def train():
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"Using device: {device}")
    sys.stdout.flush()

    if USE_MIXED_DATA:
        train_dataset, val_dataset = get_mixed_dataset(TRAIN_SPLIT, VALID_SPLIT)
    else:
        train_dataset = CLPDDataset(split_file=TRAIN_SPLIT)
        val_dataset = CLPDDataset(split_file=VALID_SPLIT)

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True,
                              collate_fn=collate_fn, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False,
                            collate_fn=collate_fn, num_workers=0)

    model = build_lprnet(pretrained_path=PRETRAINED_PATH).to(device)

    criterion = nn.CTCLoss(blank=NUM_CLASSES - 1, reduction='mean')
    writer = SummaryWriter(LOG_DIR)

    best_acc = 0.0
    global_step = 0

    freeze_epochs = 10
    unfreeze_epochs = EPOCHS - freeze_epochs

    print(f"\n=== 阶段一：冻结骨干网络，仅训练输出层 ({freeze_epochs} epochs) ===")
    sys.stdout.flush()

    for param in model.backbone.parameters():
        param.requires_grad = False

    optimizer_stage1 = optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    scheduler_stage1 = optim.lr_scheduler.StepLR(optimizer_stage1, step_size=5, gamma=0.1)

    for epoch in range(freeze_epochs):
        train_loss, train_acc, global_step = train_epoch(
            model, train_loader, criterion, optimizer_stage1, device, writer, global_step, is_train=True
        )
        val_loss, val_acc, _ = train_epoch(
            model, val_loader, criterion, optimizer_stage1, device, writer, global_step, is_train=False
        )

        scheduler_stage1.step()

        writer.add_scalar('Train/Loss_Epoch', train_loss, epoch)
        writer.add_scalar('Train/Accuracy', train_acc, epoch)
        writer.add_scalar('Valid/Loss', val_loss, epoch)
        writer.add_scalar('Valid/Accuracy', val_acc, epoch)

        print(f"Epoch [{epoch+1}/{freeze_epochs}] (Stage 1)")
        print(f"  Train Loss: {train_loss:.4f}, Train Acc: {train_acc:.4f}")
        print(f"  Valid Loss: {val_loss:.4f}, Valid Acc: {val_acc:.4f}")
        print(f"  Learning Rate: {scheduler_stage1.get_last_lr()[0]:.6f}")
        print()
        sys.stdout.flush()

        if val_acc > best_acc:
            best_acc = val_acc
            model_path = os.path.join(MODEL_SAVE_DIR, 'lprnet_best.pth')
            torch.save({
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer_stage1.state_dict(),
                'accuracy': best_acc,
            }, model_path)
            print(f"  Best model saved to {model_path}")

    print(f"\n=== 阶段二：解冻全部网络，全量微调 ({unfreeze_epochs} epochs) ===")
    sys.stdout.flush()

    for param in model.backbone.parameters():
        param.requires_grad = True

    optimizer_stage2 = optim.Adam(model.parameters(), lr=LEARNING_RATE / 10, weight_decay=WEIGHT_DECAY)
    scheduler_stage2 = optim.lr_scheduler.StepLR(optimizer_stage2, step_size=15, gamma=0.1)

    for epoch in range(unfreeze_epochs):
        total_epoch = freeze_epochs + epoch
        train_loss, train_acc, global_step = train_epoch(
            model, train_loader, criterion, optimizer_stage2, device, writer, global_step, is_train=True
        )
        val_loss, val_acc, _ = train_epoch(
            model, val_loader, criterion, optimizer_stage2, device, writer, global_step, is_train=False
        )

        scheduler_stage2.step()

        writer.add_scalar('Train/Loss_Epoch', train_loss, total_epoch)
        writer.add_scalar('Train/Accuracy', train_acc, total_epoch)
        writer.add_scalar('Valid/Loss', val_loss, total_epoch)
        writer.add_scalar('Valid/Accuracy', val_acc, total_epoch)

        print(f"Epoch [{total_epoch+1}/{EPOCHS}] (Stage 2)")
        print(f"  Train Loss: {train_loss:.4f}, Train Acc: {train_acc:.4f}")
        print(f"  Valid Loss: {val_loss:.4f}, Valid Acc: {val_acc:.4f}")
        print(f"  Learning Rate: {scheduler_stage2.get_last_lr()[0]:.6f}")
        print()
        sys.stdout.flush()

        if val_acc > best_acc:
            best_acc = val_acc
            model_path = os.path.join(MODEL_SAVE_DIR, 'lprnet_best.pth')
            torch.save({
                'epoch': total_epoch,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer_stage2.state_dict(),
                'accuracy': best_acc,
            }, model_path)
            print(f"  Best model saved to {model_path}")

    final_path = os.path.join(MODEL_SAVE_DIR, 'lprnet_final.pth')
    torch.save({
        'epoch': EPOCHS,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer_stage2.state_dict(),
    }, final_path)
    print(f"Final model saved to {final_path}")

    writer.close()


if __name__ == '__main__':
    train()