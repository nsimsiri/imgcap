import torch
import matplotlib.pyplot as plt
import numpy as np
import argparse
import pickle
import os
from torch.autograd import Variable
from torchvision import transforms
from build_vocab import Vocabulary
from att_model import EncoderCNN, DecoderRNN

from PIL import Image

def to_var(x, volatile=False):
    if torch.cuda.is_available():
        x = x.cuda()
    return Variable(x, volatile=volatile)

def load_image(image_path, transform=None):
    image = Image.open(image_path)
    image = image.resize([224, 224], Image.LANCZOS)

    if transform is not None:
        image = transform(image).unsqueeze(0)

    return image

def main(args, show_img=False):
    # Image preprocessing

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.485, 0.456, 0.406),
                             (0.229, 0.224, 0.225))])

    # Load vocabulary wrapper
    # vocab = args.vocab;
    # if (args.vocab is None):
    with open(args.vocab_path, 'rb') as f:
        vocab = pickle.load(f)

    # Build Models
    # encoder = args.encoder;
    # decoder = args.decoder;
    # if (args.encoder is None and args.decoder is None):
    encoder = EncoderCNN(args.embed_size)
    encoder.eval()  # evaluation mode (BN uses moving mean/variance)
    decoder = DecoderRNN(args.embed_size, args.hidden_size,
                         len(vocab), args.num_layers, 1)


    # Load the trained model parameters
    encoder.load_state_dict(torch.load(args.encoder_path))
    decoder.load_state_dict(torch.load(args.decoder_path))

    # Prepare Image
    image = load_image(args.image, transform)
    image_tensor = to_var(image, volatile=True)

    # If use gpu
    if torch.cuda.is_available():
        encoder.cuda()
        decoder.cuda()

    # Generate caption from image
    projected_feature, feature = encoder(image_tensor)
    sampled_ids = decoder.sample(projected_feature, feature)
    sampled_ids = sampled_ids.cpu().data.numpy()

    # Decode word_ids to words
    sampled_caption = []
    for word_id in sampled_ids:
        word = vocab.idx2word[word_id]
        sampled_caption.append(word)
        if word == '<end>':
            break
    sentence = ' '.join(sampled_caption)
    # Print out image and generated caption.
    if show_img:
        image = Image.open(args.image)
        plt.imshow(np.asarray(image))
    return sentence, encoder, decoder, vocab;

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=str, required=True,
                        help='input image for generating caption')  #COCO_val2014_000000014547.jpg
    parser.add_argument('--encoder_path', type=str, default='./models/ATT/att-encoder-1-1.pkl',
                        help='path for trained encoder')
    parser.add_argument('--decoder_path', type=str, default='./models/ATT/att-decoder-1-1.pkl',
                        help='path for trained decoder')
    parser.add_argument('--vocab_path', type=str, default='./data/vocab.pkl',
                        help='path for vocabulary wrapper')

    # Model parameters (should be same as paramters in train.py)
    parser.add_argument('--embed_size', type=int , default=16,
                        help='dimension of word embedding vectors')
    parser.add_argument('--hidden_size', type=int , default=32,
                        help='dimension of lstm hidden states')
    parser.add_argument('--num_layers', type=int , default=1 ,
                        help='number of layers in lstm')

    args = parser.parse_args()
    print args
    main(args)