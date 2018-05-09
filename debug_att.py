import torch
import torch.nn as nn
import torchvision.models as models
from torch.nn.utils.rnn import pack_padded_sequence
from torch.autograd import Variable
import torch.nn.functional as F
import numpy as np;
from OldModel import *;
import sys;

RESNET_SHAPE = (2048, 7, 7)
RESNET_LAYER = -2
MAX_T = 50;
def to_var(x, volatile=False, ):
    if torch.cuda.is_available():
        x = x.cuda()
    return Variable(x, volatile=volatile)

class E2ncoderCNN(nn.Module):
    def __init__(self, embed_size):
        """Load the pretrained ResNet-152 and replace top fc layer."""
        super(EncoderCNN, self).__init__()
        resnet = models.resnet152(pretrained=True)
        modules = list(resnet.children())[:RESNET_LAYER]      # delete the last fc layer.
        self.resnet = nn.Sequential(*modules)
        # self.linear = nn.Linear(resnet.fc.in_features*7*7, embed_size)
        self.LD = reduce(lambda x,y:x*y, RESNET_SHAPE);
        self.L = RESNET_SHAPE[1]*RESNET_SHAPE[2];
        self.D = RESNET_SHAPE[0];
        self.linear = nn.Linear(self.D, self.D)
        self.bn = nn.BatchNorm1d(embed_size, momentum=0.01)
        self.bn2D = nn.BatchNorm2d(self.D, momentum=0.01)
        self.init_weights();

    def init_weights(self):
        """Initialize the weights."""
        # self.linear.weight.data.normal_(0.0, 0.02)
        torch.nn.init.xavier_uniform_(self.linear.weight)
        self.linear.bias.data.fill_(0)

    #(N,L,D) --> (N,L,D)
    def _project_features(self,features):
        features_flat = features.contiguous().view(-1, self.D);
        features_proj = self.linear(features_flat);
        features_proj = features.contiguous().view(-1, self.L, self.D);
        return features_proj


    def forward(self, images):
        """Extract the image feature vectors."""
        features = self.resnet(images)
        features = to_var(Variable(features.data)) #(N, D, L', L') where L' = sqrt(L)
        features = self.bn2D(features); # (N, D, L', L')

        att_features = features.view((features.shape[0], RESNET_SHAPE[0], \
                                      RESNET_SHAPE[1]*RESNET_SHAPE[2]));
        att_features = att_features.permute(0,2,1); # (N,L,D)

        features_proj = self._project_features(att_features);
        return features_proj, att_features;

class EncoderCNN(nn.Module):
    def __init__(self, embed_size):
        """Load the pretrained ResNet-152 and replace top fc layer."""
        super(EncoderCNN, self).__init__()
        resnet = models.resnet152(pretrained=True)
        modules = list(resnet.children())[:-1]      # delete the last fc layer.
        self.resnet = nn.Sequential(*modules)
        self.linear = nn.Linear(resnet.fc.in_features, embed_size)
        self.bn = nn.BatchNorm1d(embed_size, momentum=0.01)
        self.init_weights()

    def init_weights(self):
        """Initialize the weights."""
        self.linear.weight.data.normal_(0.0, 0.02)
        self.linear.bias.data.fill_(0)

    def forward(self, images):
        """Extract the image feature vectors."""
        features = self.resnet(images)
        features = Variable(features.data)
        features = features.view(features.size(0), -1)
        features = self.bn(self.linear(features))
        return None, features

class DecoderRNN(nn.Module):
    def __init__(self, embed_size,hidden_size, vocab_size, num_layers, batch_size=5):
        """Set the hyper-parameters and build the layers."""
        super(DecoderRNN, self).__init__()
        self.N = batch_size;
        self.V = vocab_size
        self.M = embed_size
        self.H =  hidden_size
        self.L = RESNET_SHAPE[1]*RESNET_SHAPE[2]; #(7 x 7)
        self.D = RESNET_SHAPE[0]; #(2048)
        self.DEBUG_feat = nn.Linear(self.M, self.H);
        self.batch_size = batch_size;
        print 'emb_size(M): ',embed_size, 'hid_size(H): ',hidden_size, \
        'voc_size(V): ',vocab_size, 'L: ', self.L, 'D: ', self.D, 'num_layers: '
        self.embed = nn.Embedding(self.V, self.M)
        self.lstm = nn.LSTM(self.M, self.H, num_layers, batch_first=True)
        self.linear = nn.Linear(self.H, self.V)
        # encode feature
        self._affine_lstm_init_h = nn.Linear(self.D, self.H);
        self._affine_lstm_init_c = nn.Linear(self.D, self.H);
        # attention sub-layers
        self._affine_feat_proj_att = nn.Linear(self.H, self.D);
        self._affine_att = nn.Linear(self.D, 1);
        # LSTM cell
        # self.lstm_cell = nn.LSTMCell(self.M + self.D, self.H);
        self.lstm_cell = nn.LSTMCell(self.M, self.H);
        # attention lstm decode sub-layers; - Equation(7)
        self._affine_decode_h = nn.Linear(self.H, self.M);
        self._affine_decode_ctx = nn.Linear(self.D, self.M);
        self._affine_decoder_out = nn.Linear(self.M, self.V);
        self.h0 = nn.Parameter(torch.zeros(self.N, self.H), requires_grad=True);
        self.c0 = nn.Parameter(torch.zeros(self.N, self.H), requires_grad=True);
        # self.word_lstm_init_h = Parameter(torch.randn(2, 20, word_lstm_dim).type(FloatTensor), requires_grad=True)
        self.init_weights();
        self.hidden_size = hidden_size;
        self.embed_size = embed_size;
        ''' in forward>
        T = n_time_step
        N = batch size
        '''

    def init_weights(self):
        """Initialize weights."""
        torch.nn.init.xavier_uniform_(self.DEBUG_feat.weight)
        self.DEBUG_feat.bias.data.fill_(0)

        self.embed.weight.data.uniform_(-0.1, 0.1)
        torch.nn.init.xavier_uniform_( self.linear.weight)
        self.linear.bias.data.fill_(0)

        # initial lstm sub-layers
        self._affine_lstm_init_h.bias.data.fill_(0)
        torch.nn.init.xavier_uniform_(self._affine_lstm_init_h.weight)
        self._affine_lstm_init_c.bias.data.fill_(0)
        torch.nn.init.xavier_uniform_(self._affine_lstm_init_c.weight)

        # attention sub-layers
        torch.nn.init.xavier_uniform_(self._affine_feat_proj_att.weight);
        torch.nn.init.xavier_uniform_(self._affine_att.weight);
        self._affine_feat_proj_att.bias.data.fill_(0);
        self._affine_att.bias.data.fill_(0);

        #attention lstm decod sub-layers
        torch.nn.init.xavier_uniform_(self._affine_decode_h.weight)
        torch.nn.init.xavier_uniform_(self._affine_decode_ctx.weight)
        torch.nn.init.xavier_uniform_(self._affine_decoder_out.weight);
        self._affine_decode_h.bias.data.fill_(0);
        self._affine_decode_ctx.bias.data.fill_(0);
        self._affine_decoder_out.bias.data.fill_(0);

    #(N, L, D) features
    def affine_lstm_init(self, features):
        relu = nn.ReLU();
        features = torch.mean(features,  1); #(N, H)
        h = self._affine_lstm_init_h(features);
        h = relu(h);

        c = self._affine_lstm_init_c(features);
        c = relu(c);
        return h, c;

    def attention_layer(self, h, projected_features, annotation_vector):
        """ Attention mechanism from show,attend,tell - equation 4,5,6 and
            section 4 for soft-attention.
            returns: context_vector = (N, D), alpha (N, L)
        """
        relu = nn.ReLU();
        softmax = nn.Softmax(dim=1); #input = (N, L)

        h_out = self._affine_feat_proj_att(h);
        h_out = h_out.unsqueeze(1);
        relu_in = projected_features + h_out;
        h_out = relu(relu_in); #(N, L, D)
        N, _ , _ = h_out.shape;
        # t = h time step, i = visual subsection
        # each i in L is an attention factor;
        e_ti = self._affine_att(h_out.contiguous().view(N * self.L, self.D)); # (N*L, D) x (D, 1)
        e_ti = e_ti.contiguous().view(N, self.L);
        alpha = softmax(e_ti);
        # 4.1.13 sum(L) { annotation_vec * }
        # apply attention weights to each region
        _weighted_anns = alpha.unsqueeze(2)*annotation_vector;
        ctx_vector = torch.sum(_weighted_anns, 1);
        return ctx_vector, alpha;

    def attention_lstm_decode_layer(self, ctx_vector, h, y_prev):
        '''
        ctx_vector = (N, D)
        h = (N, H)
        y_prev = (N, M)
        '''
        new_words = torch.max(y_prev, 1)[1]; #(N, 1);
        y_i = self.embed(new_words); #(N,1) embed ();
        decode_h = self._affine_decode_h(h);
        decode_ctx = self._affine_decode_ctx(ctx_vector);
        # print 'decode_h', decode_h.shape;
        # print 'decode_ctx', decode_ctx.shape
        # print 'y_prev.shape',y_prev.shape
        decode_in = decode_h + decode_ctx + y_i;
        decode_out =  self._affine_decoder_out(decode_in);
        # print 'decode_out', decode_out.shape;
        return decode_out;

    # projected_features (N,L,D), features (N,L,D),
    def forward(self, projected_features, features, captions, lengths):
        """Decode image feature vectors and generates captions.
            projected_features.shape = (N, L*D), i.e (5, 49*2048 = 100352)
            features = (N, L, D) i.e (N, 49, 2048)
        """
        N, T = captions.shape;
        embeddings = self.embed(captions) # = (N, M)
        # next_h, next_c = self.affine_lstm_init(features); # (N,H)
        # next_h = self.DEBUG_feat(features);
        next_h = to_var(torch.zeros(N, self.H));
        next_c = to_var(torch.zeros(N, self.H));
        alphas = [];
        h_list = []
        y_i = to_var(Variable(torch.zeros(N, self.V)));
        embeddings = torch.cat((features.unsqueeze(1), embeddings), 1)n
        for i in range(0,T):
        #     # ctx_vector, alpha = self.attention_layer(next_h, projected_features, features);
            # embedding_i = torch.cat((embeddings[:,i,:], ctx_vector), 1);
            embedding_i = embeddings[:,i,:]
        #     # expects input = (N, M), h,c = (N, H)
            next_h, next_c = self.lstm_cell(embedding_i, (next_h, next_c));
        #     # y_i = self.attention_lstm_decode_layer(ctx_vector, next_h, y_i); #(N, V)
            # h_list.append(y_i);
            h_list.append(next_h);
        outputs = torch.cat(h_list)
        outputs = outputs.contiguous().view((N, T, -1));
        outputs = self.linear(outputs);
        # outputs = outputs.contiguous().view((N, T, self.V));
        # print 'outputs',outputs.shape;
        return outputs;

    def sample(self, features):
        ''''<start>': 1
        <end>': 2
        '''
        N = features.shape[0];
        # inputs = features.unsqueeze(0)
        sampled_ids = []
        # start = torch.cuda.LongTensor([1]*N).cuda();
        embedding_i = features;#self.embed(start);
        next_h = to_var(Variable(torch.zeros(1, self.H)));
        next_c = to_var(Variable(torch.zeros(1, self.H)));
        for i in range(20):
            # embedding_i = embeddings[:,i,:];
            # expects input = (N, M), h,c = (N, H)
            next_h, next_c = self.lstm_cell(embedding_i, (next_h, next_c));
            word_idx = torch.max(next_h, 1)[1];
            sampled_ids.append(word_idx);
            embedding_i = self.embed(word_idx);

        sampled_ids = torch.cat(sampled_ids, 0);
        sampled_ids = sampled_ids.squeeze()
        return sampled_ids;

'''
    def sample(self, features, projected_features, states=None, vocab=None):
        # <start>: 1
        # <end>: 2
        #
        print 'sampling'
        alphas = []
        N = features.shape[0];
        next_h, next_c = self.affine_lstm_init(features); # (N,H)
        sampled_ids = []
        start = torch.cuda.LongTensor([1]*N).cuda();
        embeddings = self.embed(start);
        y_i = to_var(Variable(torch.zeros(N, self.V)));
        for i in range(20):                                      # maximum sampling length
            alphas = [];
            h_list = []
            ctx_vector, alpha = self.attention_layer(next_h, projected_features, features);
            embedding_i = torch.cat((embeddings, ctx_vector), 1);

            # expects input = (N, M), h,c = (N, H)
            next_h, next_c = self.lstm_cell(embedding_i, (next_h, next_c));
            y_i = self.attention_lstm_decode_layer(ctx_vector, next_h, y_i); #(N, V)
            word_idx = torch.max(y_i, 1)[1];
            sampled_ids.append(word_idx)
            alphas.append(alpha);
            embeddings = self.embed(word_idx);
        sampled_ids = torch.cat(sampled_ids, 0);
        sampled_ids = sampled_ids.squeeze()
        return sampled_ids;
'''

'''
    def sample(selff, features, states=None):
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
'''