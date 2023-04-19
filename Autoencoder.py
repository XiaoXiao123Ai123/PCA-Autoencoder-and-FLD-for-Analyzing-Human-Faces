"""
Autoencoder(非线性)方法
"""
import os
import numpy as np
import argparse
import scipy.io as sio
import pickle
import matplotlib.pyplot as plt
from mywarper import warp
from skimage import io, transform

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, utils
from torch.autograd import Variable

# 规定相应参数
# parser = argparse.ArgumentParser(description='stat231_project1')
parser = argparse.ArgumentParser(description='Proj1')
parser.add_argument('--epochs', type=int, default=300)     # 迭代次数设置为300
parser.add_argument('--batch_size', type=int, default=100)        # batchsize设置为100
parser.add_argument('--seed', type=int, default=12345)
parser.add_argument('--device', type=int, default=0)
parser.add_argument('--image_dir', type=str, default='./images/')
parser.add_argument('--landmark_dir', type=str, default='./landmarks/')
parser.add_argument('--male_img_dir', type=str, default='./male_images/')
parser.add_argument('--female_img_dir', type=str, default='./female_images/')
parser.add_argument('--male_landmark', type=str, default='./male_landmarks/')
parser.add_argument('--female_landmark', type=str, default='./female_landmarks/')
parser.add_argument('--path', type=str, default='./results/model/')
parser.add_argument('--log', type=str, default='./results/log/')
parser.add_argument('--appear_lr', type=float, default=7e-4)   # 外观重构学习率为7e-4
parser.add_argument('--landmark_lr', type=float, default=1e-4)   # 地标重构学习率为1e-4

# Read Dataset
class data_reader(object):
    def __init__(self, root_dir, file_str_len, origin_name, file_format):
        self.root_dir = root_dir
        self.file_str_len = file_str_len
        self.origin_name = origin_name
        self.file_format = file_format

    def read(self, split, read_type):
        files_len = len([name for name in os.listdir(self.root_dir)
                        if os.path.isfile(os.path.join(self.root_dir, name))])
        counter = 0
        idx = counter
        dataset = []
        train_dataset = []
        test_dataset = []
        while counter < files_len:
            name = self.origin_name + str(idx)
            if len(name) > self.file_str_len:
                name = name[len(name)-self.file_str_len:]
            try:
                if read_type == 'image':
                    data = io.imread(self.root_dir + name + self.file_format)
                elif read_type == 'landmark':
                    mat_data = sio.loadmat(self.root_dir + name + self.file_format)

                    data = mat_data['lms']
                dataset.append(data)
                counter += 1
            except FileNotFoundError:
                pass
            idx += 1
        train_dataset = dataset[:split]
        test_dataset = dataset[split:]
        return train_dataset, test_dataset

# Construct Dataset
class ImgToTensor(object):
    def __call__(self, sample):
        sample = sample.transpose((2, 0, 1))
        return torch.tensor(sample, dtype=torch.float32)/255

class LandmarkToTensor(object):
    def __call__(self, sample):
        return torch.tensor(sample, dtype=torch.float32)/128

class dataset_construct(Dataset):
    def __init__(self, dataset, transform=None):
        self.dataset = dataset
        self.transform = transform

    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        sample_data = self.dataset[idx]
        if self.transform:
            sample_data = self.transform(sample_data)
        return sample_data


'''
CONV layer: computes output of neurons connected to local regions in input,
each layer computing a dot product between its weights and the small region
to which it is connected in the input volume. This may result in volume such
as [32x32x12] if we decided to use 12 filters.
ReLU layer: applies an element-wise activation function, such as the max(0,x)
thresholding at zero. This leaves the size of the volume unchanged ([32x32x12]).
POOL layer: performs a downsampling operation along the spatial dimensions (width, height),
resulting in volume such as [16x16x12].
FC (fully-connected) layer: computes the class scores, resulting in volume of size [1x1x10],
in which each of the 10 numbers corresponds to a class score, e.g. among the 10 categories of CIFAR-10.
As with ordinary Neural Networks, each neuron in this layer is connected to all numbers in previous volume.
CONV/FC: perform transformations based on activations of input volume and weights and biases of neurons.
Parameters are trained with gradient descent so that class scores are consistent with labels in training set.
ReLU/POOL: implement a fixed function
CONV/FC/POOL: may have hyperparameters (ReLU does not)
'''

APP_Z = []
GEO_Z = []

# Convolutional architecture, reconstructs and generates 2-d face images
class appearance_autoencoder(nn.Module):
    def __init__(self):
        super(appearance_autoencoder, self).__init__()
        self.encoder = nn.Sequential(
            # Applies a 2D convolution over input signal composed of several input planes
            # params: (in_channels, out_channels, kernel_size, stride=1, padding=0, ...)
            nn.Conv2d(3, 16, kernel_size=3, stride=2, padding=1),
            nn.LeakyReLU(),
            nn.Conv2d(16, 32, kernel_size=3, stride=2, padding=1),
            nn.LeakyReLU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
            nn.LeakyReLU(),
            nn.Conv2d(64, 128, kernel_size=3, stride=2, padding=1),
            nn.LeakyReLU(),
        )
        self.fc1 = nn.Sequential(
            nn.Linear(128 * 8 * 8, 50),
            nn.LeakyReLU(),
        )
        self.decoder = nn.Sequential(
            # De-Conv in PyTorch: ConvTranspose2d
            nn.ConvTranspose2d(50, 128, kernel_size=8, stride=1),
            nn.LeakyReLU(),
            nn.ConvTranspose2d(128, 64, kernel_size=4, stride=2, padding=1),
            nn.LeakyReLU(),
            nn.ConvTranspose2d(64, 32, kernel_size=4, stride=2, padding=1),
            nn.LeakyReLU(),
            nn.ConvTranspose2d(32, 16, kernel_size=4, stride=2, padding=1),
            nn.LeakyReLU(),
            nn.ConvTranspose2d(16 ,3, kernel_size=4, stride=2, padding=1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        x = self.encoder(x)
        z = self.fc1(x.view(-1, 128 * 8 * 8)) # torch.Size([40, 50])
        x_recon = self.decoder(z.view(-1, 50, 1, 1))
        return x_recon, z

    def given_latent(self, x):
        x = x.view(-1,50,1,1)
        x_recon = self.decoder(x)
        return x_recon

# Fully-connected architecture, reconstructs and generates landmarks
class landmark_autoencoder(nn.Module):
    def __init__(self):
        super(landmark_autoencoder, self).__init__()
        self.encoder = nn.Sequential(
            # Applies a linear transformation to the incoming data: y = x*A' + b
            nn.Linear(68 * 2, 100),
            # Applies element-wise LeakyReLU(x) = max(0,x) + negative_slope * min(0,x)
            nn.LeakyReLU(),
            nn.Linear(100, 10),
            nn.LeakyReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(10, 100),
            nn.LeakyReLU(),
            nn.Linear(100, 68 * 2),
            # Applies element-wise Sigmoid(x) = 1 / (1 + exp(−x))
            nn.Sigmoid(),
        )

    def forward(self, x):
        x = x.view(-1, 68 * 2)
        z = self.encoder(x) # torch.Size([20, 10])
        x_recon = self.decoder(z)
        x = x.view(-1, 68 * 2)
        return x_recon, z

    def given_latent(self, x):
        x_recon = self.decoder(x)
        x_recon = x_recon.view(-1,68,2)
        return x_recon

# aytocoder训练
class autoencoder(object):
    def __init__(self, appear_lr, landmark_lr, use_cuda):
        self.appear_model = appearance_autoencoder()
        self.landmark_model = landmark_autoencoder()
        self.use_cuda = use_cuda
        if use_cuda:
            self.appear_model.cuda()
            self.landmark_model.cuda()
        self.criterion = nn.MSELoss() # MSELoss loss = (x_n − y_n)^2
        self.appear_optim = optim.Adam(self.appear_model.parameters(), lr=appear_lr)
        self.landmark_optim = optim.Adam(self.landmark_model.parameters(), lr=landmark_lr)

    # 训练外观重构模型
    def train_appear_model(self, epochs, trainloader):
        self.appear_model.train()
        epoch = 0
        # TODO: Train appearance autoencoder
        for epoch in range(0, epochs):
            training_loss = 0
            for x in trainloader:
                if self.use_cuda:
                    x = x.cuda()

                self.appear_optim.zero_grad()
                x_recon,z = self.appear_model(x)
                loss = self.criterion(x_recon, x)
                loss.backward()
                self.appear_optim.step()

                training_loss += loss.item()
            print('Image Training Epoch:{}, Loss:{:.6f}'.format(epoch, training_loss/len(trainloader)))

    # 训练地标模型
    def train_landmark_model(self, epochs, trainloader):
        self.landmark_model.train()
        epoch = 0
        # TODO: Train landmark autoencoder
        training_loss = 0
        for epoch in range(0, epochs):
            training_loss = 0
            for x in trainloader:
                if self.use_cuda:
                    x = x.cuda()

                self.landmark_optim.zero_grad()
                x_recon, z = self.landmark_model(x)
                loss = self.criterion(x_recon, x)
                loss.backward()
                self.landmark_optim.step()
                training_loss += loss.item()
            print('Landmark Training Epoch:{}, Loss:{:.6f}'.format(epoch, training_loss / len(trainloader)))

    # 测试外观模型
    def test_appear_model(self, testloader):
        self.appear_model.eval()
        # TODO: Test appearance autoencoder
        testing_loss = 0
        appear_recon = []
        appear_latent = []
        for x in testloader:
            if self.use_cuda:
                x = x.cuda()

            x_recon, z = self.appear_model(x)
            loss = self.criterion(x_recon, x)
            testing_loss += loss.item()
            appear_recon.append(x_recon.data.cpu().numpy())
            appear_latent.append(z.data.cpu().numpy())
        # print('Landmark Training Epoch:{}, Loss:{:.6f}'.format(testing_loss/len(testloader)))
        return (appear_recon, appear_latent, testing_loss)

    # 测试地标模型
    def test_landmark_model(self, testloader):
        self.appear_model.eval()
        # TODO: Test appearance autoencoder
        testing_loss = 0
        landmark_recon = []
        landmark_latent = []
        for x in testloader:
            if self.use_cuda:
                x = x.cuda()

            x_recon, z = self.landmark_model(x)
            loss = self.criterion(x_recon, x)
            testing_loss += loss.item()
            landmark_recon.append(x_recon.data.cpu().numpy())
            landmark_latent.append(z.data.cpu().numpy())
        # print('Landmark Training Epoch:{}, Loss:{:.6f}'.format(testing_loss/len(testloader)))
        return (landmark_recon, landmark_latent, testing_loss)

    def appear_given_fc(self, fcloader):
        self.appear_fc_recon = []
        for fc in fcloader:
            if self.use_cuda:
                fc = fc.cuda()
            recon = self.appear_model.given_latent(fc)
            self.appear_fc_recon.append(recon.data.cuda().numpy())

    def landmark_given_fc(self, fcloader):
        self.landmark_fc_recon = []
        for fc in fcloader:
            if self.use_cuda:
                fc = fc.cuda()
            recon = self.landmark_model.given_latent(fc)
            self.landmark_fc_recon.append(recon.data.cuda().numpy())

def save_data(data, filename):
    f = open(filename, 'wb')
    pickle.dump(data, f)
    f.close()

def get_data(filename):
    f = open(filename, 'rb')
    data = pickle.load(f)
    f.close()
    return data

# 进行地标重构
def reconstruct_landmarks(ae, landmark_testloader):
    recon_landmarks, lm_latent,loss = ae.test_landmark_model(landmark_testloader)
    print('Loss for Reconstructing Geometry of Test Landmarks: ', loss)
    return recon_landmarks

# 进行可扭曲图像重构
def reconstruct_warped_imgs(ae, warped_face_testloader):
    recon_appear_imgs, recon_latent, loss = ae.test_appear_model(warped_face_testloader)
    print('Loss for Reconstructing Appearance of Warped Test Images: ', loss)
    return recon_appear_imgs

def calc_mean(A):
    A_sum = np.zeros(np.shape(A[0]))
    for item in A:
        A_sum += item
    return A_sum / len(A)

def warp_imgs_to_mean(imgs, landmarks, landmark_mean):
    return [warp(img, landmarks[i], landmark_mean) for i, img in enumerate(imgs)]

# recon_appear_imgs: (2,) where tensor (100, 3, 128, 128)
# recon_landmarks: (2,) where tensor (100, 136)
def warp_imgs_to_landmarks(recon_appear_imgs, landmark_src, recon_landmarks):
    imgs = []
    for batch_i, batch in enumerate(recon_appear_imgs):
        for i, img in enumerate(batch):
            img = torch.from_numpy(img)
            img = img.permute(1, 2, 0).detach().numpy()
            recon_landmark = np.reshape(torch.from_numpy(recon_landmarks[batch_i][i]).detach().numpy(), (68, 2))
            recon_landmark=np.array(recon_landmark)
            recon_img = warp(img, landmark_src, recon_landmark)
            imgs.append(recon_img)
    return imgs

# img_landmark:  (68, 2)
# recon_landmarks: (1,) where tensor (20, 136)
def warp_img_to_interpolated_landmarks(images, img_landmark, recon_landmarks):
    imgs = []
    for i, landmark in enumerate(recon_landmarks):
        recon_landmark = np.reshape(landmark, (68, 2))
        recon_img = warp(images[i], img_landmark, recon_landmark)
        imgs.append(recon_img)
    return imgs

def reshape_landmarks(landmarks):
    return [np.asarray(landmark).flatten() for landmark in landmarks]

def get_warped_face_loader(warped_imgs, shuffle=True):
    warped_face_set = dataset_construct(warped_imgs, transform=transforms.Compose([ImgToTensor()]))
    return torch.utils.data.DataLoader(warped_face_set, batch_size=args.batch_size, shuffle=shuffle, num_workers=2)

def get_interpolation_landmark_loader():
    landmark_testset = dataset_construct(reshape_landmarks([landmark_test[4]] * 20), transform=transforms.Compose([LandmarkToTensor()]))
    return torch.utils.data.DataLoader(landmark_testset, batch_size=args.batch_size, shuffle=False, num_workers=2)

def disp_recon_imgs(recon_imgs, orig_imgs):
    f, axes = plt.subplots(4, 5)
    for i, img in enumerate(recon_imgs):
        img = img.clip(min=0, max=1)
        axes[i // 5, i % 5].imshow(img)
    plt.show()

    f, axes = plt.subplots(4, 5)
    for i, img in enumerate(orig_imgs):
        axes[i // 5, i % 5].imshow(img)
    plt.show()

# interpolated_imgs for appearance: (40, 3, 128, 128)
# interpolated_imgs for landmarks: (20, 128, 128, 3)
def disp_interpolated_imgs(interpolated_imgs, appearance=True):
    rows = 4 if appearance else 10
    f, axes = plt.subplots(rows, 10)
    for i, img in enumerate(interpolated_imgs):
        if appearance:
            img = torch.from_numpy(img)
            img = img.permute(1, 2, 0).detach().numpy().clip(min=0, max=1)
        axes[i // 10, i % 10].imshow(img)
    plt.show()

# Z for appearance: (2402,) where tensor (100, 50)
# Z for geometry: (2402,) where tensor (100, 10)
def get_interpolations(Z, num_latent_var, num_dimensions):
    mins = torch.min(Z[0], 0)[0] # dim 0 is columns, becomes torch.Size([120150])
    maxes = torch.max(Z[0], 0)[0]
    for x in Z:
        mins = torch.cat((mins, torch.min(x, 0)[0]))
        maxes = torch.cat((maxes, torch.max(x, 0)[0]))

    mins = torch.reshape(mins, (-1, num_latent_var)) # torch.Size([2403, num_latent_var])
    maxes = torch.reshape(maxes, (-1, num_latent_var))
    dim_mins = torch.min(mins, 0)[0] # torch.Size([num_latent_var])
    dim_maxes = torch.max(maxes, 0)[0]

    # print('dim mins: ', dim_mins)
    # print('dim maxes: ', dim_maxes)
    diffs = dim_maxes - dim_mins
    # print('diffs: ', diffs)

    # get indices of 4 dimensions of appearance and 2 of geometry with maximal variance
    dim_i = np.argsort(diffs.detach().numpy())[::-1][:num_dimensions]
    # print('dim_i: ', dim_i)
    save_data(dim_i, 'landmark_z_indices.pckl')

    dim_interpolations = []
    for i in dim_i:
        dim_interpolations.append(np.linspace(dim_mins[i].detach().numpy(), dim_maxes[i].detach().numpy(), 10))
    # print('dim_interpolations: ', dim_interpolations)
    return dim_interpolations

# img: (128, 128, 3)
def interpolate_img_appear(ae, img, num_interpolations):
    # Warp img into mean position (result: (40, 128, 128, 3))
    # Reconstruct appearance (result: (1,) where tensor (40, 3, 128, 128))
    landmark_mean = calc_mean(landmark_train)
    warped_imgs = warp_imgs_to_mean([img] * num_interpolations, [landmark_test[4]] * num_interpolations, landmark_mean)
    recon_appear_imgs = reconstruct_warped_imgs(ae, get_warped_face_loader(warped_imgs, False))
    return recon_appear_imgs

def interpolate_img_landmarks(ae, img, num_interpolations):
    # Warp img into mean position (result: (20, 128, 128, 3))
    # Reconstruct appearance (result: (1,) where tensor (20, 3, 128, 128))
    landmark_mean = calc_mean(landmark_train)
    warped_imgs = warp_imgs_to_mean([img] * num_interpolations, [landmark_test[4]] * num_interpolations, landmark_mean)
    # recon_appear_imgs = reconstruct_warped_imgs(ae, get_warped_face_loader(warped_imgs, False))


    # Reconstructed landmarks (result: (1,) where tensor (20, 136))
    recon_landmarks = reconstruct_landmarks(ae, get_interpolation_landmark_loader())
    # print(recon_landmarks[0][0].mean())
    # print(recon_landmarks[0][1].mean())
    # print(recon_landmarks[0][2].mean())
    # print(recon_landmarks[0][3].mean())
    # print(recon_landmarks[0][4].mean())


    # Warp a chosen face by the generated reconstructed landmarks
    # recon_imgs = warp_imgs_to_landmarks(recon_appear_imgs, landmark_test[4], recon_landmarks)
    # return warp_img_to_interpolated_landmarks([img] * 100, landmark_test[4], landmark_test[:100])
    return warp_img_to_interpolated_landmarks([img] * 100, landmark_test[4], landmark_test[:100])
def run_autoencoder():

    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # face_trset = dataset_construct(images_train, transform=transforms.Compose([ImgToTensor()]))
    # face_testset = dataset_construct(images_test, transform=transforms.Compose([ImgToTensor()]))
    # face_trloader = torch.utils.data.DataLoader(face_trset, batch_size=args.batch_size, shuffle=True, num_workers=2)
    # face_testloader = torch.utils.data.DataLoader(face_testset, batch_size=args.batch_size, shuffle=False, num_workers=2)
    landmark_trset = dataset_construct(reshape_landmarks(landmark_train), transform=transforms.Compose([LandmarkToTensor()]))
    landmark_testset = dataset_construct(reshape_landmarks(landmark_test), transform=transforms.Compose([LandmarkToTensor()]))
    landmark_trloader = torch.utils.data.DataLoader(landmark_trset, batch_size=args.batch_size, shuffle=True, num_workers=2)
    landmark_testloader = torch.utils.data.DataLoader(landmark_testset, batch_size=args.batch_size, shuffle=False, num_workers=2)

    # --------------------------------- Autoencoder: Question 1 ----------------------------------

    landmark_mean = calc_mean(landmark_train)
    # landmark_mean = calc_mean(landmark_test)
    '''
    # Train landmark model w/ training landmarks
    ae = autoencoder(args.appear_lr, args.landmark_lr, 0)
    ae.train_landmark_model(args.epochs, landmark_trloader)

    # Warp training images into mean position
    # Train appearance model w/ warped images
    warped_tr_imgs = warp_imgs_to_mean(images_train, landmark_train, landmark_mean)
    ae.train_appear_model(args.epochs, get_warped_face_loader(warped_tr_imgs))
    '''
    # ae = autoencoder(args.appear_lr, args.landmark_lr, 0)
    # save_data(ae, 'autoencoder.pckl')

    ae = get_data('autoencoder.pckl')
    ae.train_landmark_model(args.epochs, landmark_trloader)
    warped_tr_imgs = warp_imgs_to_mean(images_train, landmark_train, landmark_mean)
    ae.train_appear_model(args.epochs, get_warped_face_loader(warped_tr_imgs))
    # save_data(ae, 'autoencoder.pckl')

    '''
    # Warp test images into mean position (result: (200, 128, 128, 3))
    # Reconstruct their appearance (result: (2,) where tensor (100, 3, 128, 128))
    # In PCA: reconstructed appearance obtained by projecting imgs onto top 50 eigen-faces
    warped_imgs = warp_imgs_to_mean(images_test, landmark_test, landmark_mean)
    recon_appear_imgs = reconstruct_warped_imgs(ae, get_warped_face_loader(warped_imgs, False))

    # Reconstructed test landmarks (result: (2,) where tensor (100, 136))
    # In PCA: recon. landmarks obtained by projecting img landmarks onto top 10 eigen-warpings
    recon_landmarks = reconstruct_landmarks(ae, landmark_testloader)

    # Warp the reconstructed appearances to the positions of reconstructed test landmarks
    recon_faces = warp_imgs_to_landmarks(recon_appear_imgs, landmark_mean, recon_landmarks)

    # Plot 20 reconstructed faces and their corresponding original faces
    disp_recon_imgs(recon_faces[10:30], images_test[10:30])
    '''

    warped_imgs = warp_imgs_to_mean(images_test, landmark_test, landmark_mean)
    recon_appear_imgs = reconstruct_warped_imgs(ae, get_warped_face_loader(warped_imgs, False))

    # Reconstructed test landmarks (result: (2,) where tensor (100, 136))
    # In PCA: recon. landmarks obtained by projecting img landmarks onto top 10 eigen-warpings
    recon_landmarks = reconstruct_landmarks(ae, landmark_testloader)

    # Warp the reconstructed appearances to the positions of reconstructed test landmarks
    recon_faces = warp_imgs_to_landmarks(recon_appear_imgs, landmark_mean, recon_landmarks)

    disp_recon_imgs(recon_faces[10:30], images_test[10:30])

    # --------------------------------- Autoencoder: Question 2 ----------------------------------

    # 选择具有最大方差的外观潜变量的前四个维度的插值实验
    appear_imgs = interpolate_img_appear(ae, images_test[4], 40)
    disp_interpolated_imgs(appear_imgs[0])

    # 选择具有最大方差的地标潜变量的前两个维度插值实验
    landmark_imgs = interpolate_img_landmarks(ae, images_test[4], 20)  # (20, 128, 128, 3)
    disp_interpolated_imgs(landmark_imgs, False)

    '''
    # Select an interpolation experiment for the first four dimensions of the appearance latent variable with the largest variance
    appear_imgs = interpolate_img_appear(ae, images_test[4], 40)
    disp_interpolated_imgs(appear_imgs[0])
    
    # Choose the first two dimension interpolation experiments for the landmark latent variable with the largest variance
    landmark_imgs = interpolate_img_landmarks(ae, images_test[4], 20)  # (20, 128, 128, 3)
    disp_interpolated_imgs(landmark_imgs, False)
    '''

def main():
    run_autoencoder()

# 定义GPU训练
args = parser.parse_args(args=[])
args.cuda = torch.cuda.is_available()
# torch.cuda.set_device(0) # was 0
device = torch.device(0)

if not os.path.exists(args.path):
    os.makedirs(args.path)
if not os.path.exists(args.log):
    os.makedirs(args.log)

if args.cuda:
    torch.cuda.manual_seed(args.seed)

face_images_reader = data_reader(args.image_dir, 6, '000000', '.jpg')
images_train, images_test = face_images_reader.read(split=800, read_type='image')

face_landmark_reader = data_reader(args.landmark_dir, 6, '000000', '.mat')
landmark_train, landmark_test = face_landmark_reader.read(split=800, read_type='landmark')

if __name__ == "__main__":
    main()
