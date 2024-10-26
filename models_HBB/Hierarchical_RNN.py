import torch
import torch.nn as nn


# from .configClass import config

# import torch.optim as optim
# import torch.nn.functional as F
# from dataLoader import load_data


# 此文件是好宝宝的多层segRNN的尝试，主要创新点是Hierarchical结构。
class Hierarch_RNN(nn.Module):
    def __init__(self, CONFIG):
        super(Hierarch_RNN, self).__init__()
        self.seq_len = CONFIG.input_length
        self.pred_len = CONFIG.output_length
        self.enc_in = CONFIG.enc_in
        # enc_in为变量数，是输入x的shape[-1]

        self.d_model = CONFIG.dmodel
        self.hidden_size = self.d_model
        self.dropout = CONFIG.dropout

        self.seg_len = CONFIG.seg_length
        self.hierarch_layers = CONFIG.hierarch_layers
        self.hierarch_scale = CONFIG.hierarch_scale

        self.seg_len_list = [self.seg_len // (self.hierarch_scale ** i) for i in range(self.hierarch_layers)]
        # seg_len_list = [96, 48, 24]
        self.d_modelSize_list = [self.d_model // (self.hierarch_scale ** i) for i in range(self.hierarch_layers)]
        #      dmodel = [512,256,128]

        self.seg_num_x = self.seq_len // self.seg_len
        self.seg_num_x_list = [self.seq_len // self.seg_len_list[i] for i in range(self.hierarch_layers)]

        self.seg_num_y = self.pred_len // self.seg_len
        self.seg_num_y_list = [self.pred_len // self.seg_len_list[i] for i in range(self.hierarch_layers)]

        # 定义embeding层，也具有多尺度，反正就是多尺度我超
        self.valueEmbedding_Hierarchical = nn.ModuleList([
            nn.Sequential(
                # 考虑一下这个要不要加一个dropout，可以以后测试一下
                nn.Linear(self.seg_len_list[i], self.d_modelSize_list[i]),
                nn.ReLU()
            )
            # dmodel = [512,256,128]
            for i in range(self.hierarch_layers)
        ])

        # 定义多尺度的GRU层
        self.gru_cells = nn.ModuleList([
            nn.GRUCell(input_size=self.d_modelSize_list[i],
                       hidden_size=self.d_modelSize_list[i],
                       bias=True)
            # dmodel = [512,256,128]
            for i in range(self.hierarch_layers)
        ])

        # 定义多尺度的输出层，这个感觉还可以呢
        self.predict_Hierarchical = nn.ModuleList([
            nn.Sequential(
                nn.Dropout(self.dropout),
                nn.Linear(self.d_modelSize_list[i], self.seg_len_list[i]),
            )
            for i in range(self.hierarch_layers)
        ])

        self.pos_emb_List = nn.ParameterList([
            nn.Parameter(torch.randn(self.seg_num_y_list[i], self.d_modelSize_list[i] // 2))
            for i in range(self.hierarch_layers)
        ])

        self.channel_emb_List = nn.ParameterList([
            nn.Parameter(torch.randn(self.enc_in, self.d_modelSize_list[i] // 2))
            for i in range(self.hierarch_layers)
        ])

    def encoder(self, x):
        batch_size = x.size(0)
        seq_last = x[:, -1:, :].detach()
        x = (x - seq_last).permute(0, 2, 1)  # b,c,s

        # 多尺寸输入嵌入===========================================
        x_seged_list = []
        for i in range(self.hierarch_layers):
            x_seged_instance = self.valueEmbedding_Hierarchical[i](
                x.reshape(-1, self.seg_num_x_list[i], self.seg_len_list[i]))
            #                        [512,256,128]                                     [10, 20, 40]          [96, 48, 24]
            x_seged_list.append(x_seged_instance)

        # encoding这里就是多尺度encoding的过程======================
        hn_list = []
        for layer in range(self.hierarch_layers):
            h_t = torch.zeros(x_seged_list[layer].shape[0], x_seged_list[layer].shape[2]).to(x.device)
            for i in range(self.seg_num_x_list[layer]):
                x_t = x_seged_list[layer][:, i, :]
                h_t = self.gru_cells[layer](x_t, h_t)
                h_t = x_t + h_t
            hn_list.append(h_t.unsqueeze(0))

        # 多尺度的可学习通道和位置输出初始化向量生成===================
        pos_emb_list = []
        for i in range(self.hierarch_layers):
            pos_emb = torch.cat([
                self.pos_emb_List[i].unsqueeze(0).repeat(self.enc_in, 1, 1),
                self.channel_emb_List[i].unsqueeze(1).repeat(1, self.seg_num_y_list[i], 1)
            ], dim=-1).view(-1, 1, self.d_modelSize_list[i]).repeat(batch_size, 1, 1)
            pos_emb_list.append(pos_emb)

        # 多尺度RNN结构的输出了属于是===============================
        RNN_output_list = []
        for i in range(self.hierarch_layers):
            layer_output_list = []
            for step in range(self.seg_num_y_list[i]):
                step_length = pos_emb_list[i].shape[0] // self.seg_num_y_list[i]
                pos_emb_input = pos_emb_list[i][step * step_length: (step + 1) * step_length][:, 0, :]
                hy = self.gru_cells[i](pos_emb_input, hn_list[i][0, :, :])
                layer_output_list.append(hy)
            out_put_this_layer = torch.stack(layer_output_list, dim=0)
            # 在第0个维度上concat输出
            RNN_output_list.append(out_put_this_layer.view(1, -1, self.d_modelSize_list[i]))

        # 最后的多尺度输出投影了属于是===============================
        output = torch.zeros(seq_last.size(0), self.pred_len, seq_last.size(2)).to(x.device)
        for i in range(self.hierarch_layers):
            y = self.predict_Hierarchical[i](RNN_output_list[i])
            y = y.view(-1, self.enc_in, self.pred_len)
            y = y.permute(0, 2, 1)
            output += (y + seq_last)
            if i == 1:
                return y + seq_last
        #     为什么这个地方不能写成 output += (y + seq_last)？？？

        return output / self.hierarch_layers

    def forward(self, x):
        # 初始化隐藏状态
        return self.encoder(x)

# 设置设备
# if __name__ == '__main__':
#     CONIFG = config()
#     model = model_dict[CONFIG.model_name](CONFIG).to(device)
