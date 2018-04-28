import torch
import torch.nn as nn
import torchvision.models as models
from torch.nn.utils.rnn import pack_padded_sequence
from torch.autograd import Variable
from OldModel import *;
import sys;

RESNET_SHAPE = (2048, 7, 7)
RESNET_LAYER = -2
class EncoderCNN(nn.Module):
    def __init__(self, embed_size):
        """Load the pretrained ResNet-152 and replace top fc layer."""
        super(EncoderCNN, self).__init__()
        resnet = models.resnet152(pretrained=True)
        modules = list(resnet.children())[:RESNET_LAYER]      # delete the last fc layer.
        self.resnet = nn.Sequential(*modules)
        print '...', resnet.fc;
        # self.linear = nn.Linear(resnet.fc.in_features*7*7, embed_size)
        self.LD = reduce(lambda x,y:x*y, RESNET_SHAPE);
        self.linear = nn.Linear(self.LD, embed_size)
        self.bn = nn.BatchNorm1d(embed_size, momentum=0.01)
        self.init_weights();

    def init_weights(self):
        """Initialize the weights."""
        self.linear.weight.data.normal_(0.0, 0.02)
        self.linear.bias.data.fill_(0)

    def forward(self, images):
        """Extract the image feature vectors."""
        features = self.resnet(images)
        features = Variable(features.data)
        print 'encoder features', features.shape;
        features = features.view(features.size(0), -1)
        print 'features2', features.shape
        proj_features = self.bn(self.linear(features))
        print 'features.shape', proj_features.shape
        return proj_features, features;


class DecoderRNN(nn.Module):
    def __init__(self, embed_size,hidden_size, vocab_size, num_layers ):
        """Set the hyper-parameters and build the layers."""
        super(DecoderRNN, self).__init__()
        print 'embed_size: ',embed_size, 'hidden_size: ',hidden_size, 'vocab_size: ',vocab_size, 'num_layers: ',num_layers
        self.embed = nn.Embedding(vocab_size, embed_size)
        self.lstm = nn.LSTM(embed_size, hidden_size, num_layers, batch_first=True)
        self.linear = nn.Linear(hidden_size, vocab_size)
        self.affine_lstm_init = nn.Linear(embed_size, hidden_size);
        self.lstm_cell = nn.LSTMCell(embed_size, hidden_size); #D, H
        self.init_weights();
        self.hidden_size = hidden_size;
        self.embed_size = embed_size;

        self.V = vocab_size
        self.M = embed_size
        self.H =  hidden_size
        ''' in forward>
        L = dim_feature[0]
        D = dim_feature[1]
        T = n_time_step
        N = batch size
        '''
    def init_weights(self):
        """Initialize weights."""
        self.embed.weight.data.uniform_(-0.1, 0.1)
        self.linear.weight.data.uniform_(-0.1, 0.1)
        self.linear.bias.data.fill_(0)
        self.affine_lstm_init.weight.data.uniform_(-0.1, 0.1)
        self.affine_lstm_init.bias.data.fill_(0)

    def forward(self, features, captions, lengths):
        """Decode image feature vectors and generates captions."""

        N, T = captions.shape;
        embeddings = self.embed(captions)
        next_c = Variable(torch.zeros(N, self.hidden_size))#.cuda() #need cuda
        next_h = self.affine_lstm_init(features);
        h_list = []
        for i in range(0,T):
            next_h, next_c = self.lstm_cell(embeddings[:,i,:], (next_h, next_c));
            h_list.append(next_h);
        hiddens = torch.cat(h_list);
        outputs = self.linear(hiddens)
        return outputs;

    def sample(self, features, states=None):
        """Samples captions for given image features (Greedy search)."""
        sampled_ids = []
        inputs = features.unsqueeze(1)
        for i in range(20):                                      # maximum sampling length
            hiddens, states = self.lstm(inputs, states)          # (batch_size, 1, hidden_size),
            outputs = self.linear(hiddens.squeeze(1))            # (batch_size, vocab_size)
            predicted = outputs.max(1)[1]
            sampled_ids.append(predicted)
            inputs = self.embed(predicted)
            inputs = inputs.unsqueeze(1)                         # (batch_size, 1, embed_size)
        sampled_ids = torch.cat(sampled_ids, 0)                  # (batch_size, 20)
        return sampled_ids.squeeze()
