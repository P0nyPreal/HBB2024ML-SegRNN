import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import StepLR

# import torch.nn.functional as F
from dataLoader import load_data
from dataLoader import data_provider
from testGRU import GRUModel
from MSEshower import plot_two_arrays
from torch.optim import lr_scheduler

filepath = "ETTh1.csv"
# Load the data
input_window = 720  # Number of time steps for the input (for long-term forecasting)
# input_window = 96  # Number of time steps for the input (for long-term forecasting)

output_window = 96
    # Number of time steps for the output (for long-term forecasting)
# output_window = 24  # Number of time steps for the output (for long-term forecasting)

seg_len = 48
# seg_len = 24


batch_size = 256
num_epochs = 30  # 训练轮数
lr = 0.001


train_dataset, train_loader = data_provider(embed='timeF', batch_size=batch_size, freq='h', root_path='./', data_path='ETTh1.csv', seq_len=720, label_len=0, pred_len=96, features='M', target='OT', num_workers=0, flag='train')
test_dataset, test_loader = data_provider(embed='timeF', batch_size=batch_size, freq='h', root_path='./', data_path='ETTh1.csv', seq_len=720, label_len=0, pred_len=96, features='M', target='OT', num_workers=0, flag='test')

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# 实例化模型
model = GRUModel(input_size=input_window, output_size=output_window, seg_len=seg_len, enc_in=7).to(device)

# 定义损失函数和优化器
criterion = nn.MSELoss()
# criterion = nn.L1Loss()

optimizer = optim.Adam(model.parameters(), lr=lr)
# scheduler = StepLR(optimizer, step_size=3, gamma=0.8)
scheduler = lr_scheduler.OneCycleLR(optimizer=optimizer,
                                    steps_per_epoch=len(train_loader),
                                    pct_start=0.3,
                                    epochs=num_epochs,
                                    max_lr=lr)

globalMSE_train = []
globalMSE_test = []


for epoch in range(num_epochs):
    model.train()
    total_loss = []
    # mse_loss_whileTrain = 0
    # total_samples_whileTrain = 0
    for X_batch, Y_batch, _, _ in train_loader:
        X_batch = X_batch.float().to(device)
        # print(X_batch.shape)
        Y_batch = Y_batch.float().to(device)
        # print(X_batch.shape)
        optimizer.zero_grad()
        # 前向传播
        outputs = model(X_batch)

        # 计算损失
        loss = criterion(outputs, Y_batch)
        total_loss.append(loss.item())

        # 反向传播和优化

        loss.backward()
        optimizer.step()

        # mse_loss_whileTrain += nn.functional.mse_loss(outputs, Y_batch, reduction='sum').item()
        # total_samples_whileTrain += Y_batch.numel()
    scheduler.step()
    avg_loss = np.average(total_loss)
    globalMSE_train.append(avg_loss)
    print(f'Epoch [{epoch + 1}/{num_epochs}], Loss: {avg_loss:.4f}')
    # mse_whileTrain = mse_loss_whileTrain / total_samples_whileTrain
    # print(f'Epoch [{epoch + 1}/{num_epochs}], MSE: {mse_whileTrain:.4f}')

    if epoch % 1 == 0:
        model.eval()  # 将模型设置为评估模式
        eval_tot_loss = []
        mse_loss = 0
        mae_loss = 0
        total_samples = 0

        # with torch.no_grad():
        # for X_batch, Y_batch in test_loader:
        for X_batch, Y_batch, _, _ in test_loader:
            X_batch = X_batch.float().to(device)
            Y_batch = Y_batch.float().to(device)

            outputs = model(X_batch)

            # 计算 MSE 和 MAE，使用 'sum' 来累加每个样本的误差
            # mse_loss += nn.functional.mse_loss(outputs, Y_batch, reduction='sum').item()
            mae_loss += nn.functional.l1_loss(outputs, Y_batch, reduction='sum').item()
            total_samples += Y_batch.numel()  # 统计总的样本数

            eval_tot_loss.append(criterion(outputs, Y_batch).item())


        # 计算平均 MSE 和 MAE
        # mse = mse_loss / total_samples
        mse = np.average(eval_tot_loss)
        mae = mae_loss / total_samples
        globalMSE_test.append(mse)
        # globalMSE_test.append(eval_tot_loss/ total_samples)

        print(f'Test MSE: {mse:.6f}, Test MAE: {mae:.6f}')


print(globalMSE_test)
print(globalMSE_train)
plot_two_arrays(globalMSE_train, globalMSE_test)