import torch
import os
from dataset import HorseZebraDataset
import sys
from utils import save_checkpoint, load_checkpoint
from torchvision import transforms
from torch.utils.data import DataLoader
#from trochvision.datasets import ImageFolder
import torch.nn as nn
import torch.optim as optim
import config
from tqdm import tqdm
from torchvision.utils import save_image
from discriminator_model import Discriminator
from generator_model import Generator

def train_fn(disc_H, disc_Z, gen_Z, gen_H, loader, opt_disc, opt_gen, l1, mse, d_scaler, g_sacler):
	loop = tqdm(loader, leave=True)

	for idx, (zebra, horse) in enumerate(loop):
		zebra = zebra.to(config.DEVICE)
		horse = horse.to(config.DEVICE)

		with torch.cuda.amp.autocast():
			fake_horse = gen_H(zebra)
			D_H_real = disc_H(horse)
			D_H_fake = disc_H(fake_horse.detach())
			D_H_real_loss = mse(D_H_real, torch.ones_like(D_H_real))
			D_H_fake_loss = mse(D_H_fake, torch.zeros_like(D_H_fake))
			D_H_loss = D_H_real_loss + D_H_fake_loss

			fake_zebra = gen_Z(horse)
			D_Z_real = disc_Z(zebra)
			D_Z_fake = disc_Z(fake_zebra.detach())
			D_Z_real_loss = mse(D_Z_real, torch.ones_like(D_Z_real))
			D_Z_fake_loss = mse(D_Z_fake, torch.zeros_like(D_Z_fake))
			D_Z_loss = D_Z_real_loss + D_Z_fake_loss

			D_loss = (D_H_loss + D_Z_loss)/2

		opt_disc.zero_grad()
		d_scaler.scale(D_loss).backward()
		d_scaler.step(opt_disc)
		d_scaler.update()

        # Train generators H and Z
		with torch.cuda.amp.autocast():

			# adversarial loss for both generators
			D_H_fake = disc_H(fake_horse)
			D_Z_fake = disc_Z(fake_zebra)
			loss_G_H = mse(D_H_fake, torch.ones_like(D_H_fake))
			loss_G_Z = mse(D_Z_fake, torch.ones_like(D_Z_fake))

			# cycle loss 
			cycle_zebra = gen_Z(fake_horse)
			cycle_horse = gen_H(fake_zebra)
			cycle_zebra_loss = l1(zebra, cycle_zebra)
			cycle_horse_loss = l1(horse, cycle_horse)

			# identity loss
			identity_zebra = gen_Z(zebra)
			identity_horse = gen_H(horse)
			identity_zebra_loss = l1(zebra, identity_zebra)
			identity_horse_loss = l1(horse, identity_horse)

			# add all togethor
			G_loss = (
				loss_G_Z
				+ loss_G_H
				+ cycle_zebra_loss * config.LAMDA_CYCLE
				+ cycle_horse_loss * config.LAMDA_CYCLE
				+ identity_horse_loss * config.LAMBDA_IDENTITY
				+ identity_zebra_loss * config.LAMBDA_IDENTITY
			)

		opt_gen.zero_grad()
		g_sacler.scale(G_loss).backward()
		g_sacler.step(opt_gen)
		g_sacler.update()
		os.makedirs("saved_images", exist_ok=True)
		if idx % 200 == 0:
			save_image(fake_horse*0.5+0.5, f"saved_images/horse_{idx}.png")
			save_image(fake_zebra*0.5+0.5, f"saved_images/zebra_{idx}.png")



def main():
	disc_H = Discriminator(in_channels=3).to(config.DEVICE)
	disc_Z = Discriminator(in_channels=3).to(config.DEVICE)
	gen_Z = Generator(img_channels=3, num_residuals=9).to(config.DEVICE)
	gen_H = Generator(img_channels=3, num_residuals=9).to(config.DEVICE)
	opt_disc =  optim.Adam(
		list(disc_H.parameters()) + list(disc_Z.parameters()),
		lr=config.LEARNING_RATE,
		betas=(0.5,0.999),
	) 

	opt_gen = optim.Adam(
		list(gen_Z.parameters()) + list(gen_H.parameters()),
		lr=config.LEARNING_RATE,
		betas=(0.5,0.999),
	)

	L1 = nn.L1Loss()
	mse = nn.MSELoss()

	if config.LOAD_MODEL:
		load_checkpoint(
			config.CHECKPOINT_GEN_H, gen_H, opt_gen, config.LEARNING_RATE,
		)

		load_checkpoint(
			config.CHECKPOINT_GEN_Z, gen_Z, opt_gen, config.LEARNING_RATE,
		)

		load_checkpoint(
			config.CHECKPOINT_CRITIC_H, disc_H, opt_disc, config.LEARNING_RATE,
		)

		load_checkpoint(
			config.CHECKPOINT_CRITIC_Z, disc_Z, opt_disc, config.LEARNING_RATE,
		)

	dataset = HorseZebraDataset(
		root_horse=config.TRAIN_DIR+"/horses", root_zebra=config.TRAIN_DIR+"/zebras", transform=config.transforms
	)
	loader = DataLoader(
		dataset,
		batch_size=config.BATCH_SIZE,
		shuffle=True,
		num_workers=config.NUM_WORKERS,
		pin_memory=True
	)
	g_scaler = torch.cuda.amp.GradScaler()
	d_scaler = torch.cuda.amp.GradScaler()

	for epoch in range(config.NUM_EPOCHS):
		
		train_fn(disc_H, disc_Z, gen_Z, gen_H, loader, opt_disc, opt_gen, L1, mse, d_scaler, g_scaler)

		if config.SAVE_MODEL:
			save_checkpoint(gen_H, opt_gen, filename=config.CHECKPOINT_GEN_H)
			save_checkpoint(gen_Z, opt_gen, filename=config.CHECKPOINT_GEN_Z)
			save_checkpoint(disc_H, opt_disc, filename=config.CHECKPOINT_CRITIC_H)
			save_checkpoint(disc_Z, opt_disc, filename=config.CHECKPOINT_CRITIC_Z)

if __name__ == "__main__":
	main()