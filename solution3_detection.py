# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Exercise 3/3: Tracking with an integer linear program (ILP)
#
# You could also run this notebook on your laptop, a GPU is not needed :).

# %% [markdown]
# This notebook was originally written by Benjamin Gallusser and Albert Dominguez Mantes.

# %% [markdown] tags=[] jp-MarkdownHeadingCollapsed=true jp-MarkdownHeadingCollapsed=true tags=[] jp-MarkdownHeadingCollapsed=true
# ## Import packages

# %%
# Force keras to run on CPU
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# Notebook at full width in the browser
from IPython.display import display, HTML
display(HTML("<style>.container { width:100% !important; }</style>"))

import sys
from urllib.request import urlretrieve
from pathlib import Path
from collections import defaultdict
from abc import ABC, abstractmethod

import matplotlib
import matplotlib.pyplot as plt
# %matplotlib inline
matplotlib.rcParams["image.interpolation"] = "none"
matplotlib.rcParams['figure.figsize'] = (12, 6)
from tifffile import imread, imwrite
from tqdm.auto import tqdm
import skimage
import pandas as pd
import scipy

from stardist import fill_label_holes, random_label_cmap
from stardist.plot import render_label
from stardist.models import StarDist2D
from stardist import _draw_polygons
from csbdeep.utils import normalize
import numpy as np
import networkx as nx
import cvxpy as cp

import networkx as nx

lbl_cmap = random_label_cmap()
# Pretty tqdm progress bars 
# ! jupyter nbextension enable --py widgetsnbextension

# %%
def plot_img_label(img, lbl, img_title="image", lbl_title="label", **kwargs):
    fig, (ai,al) = plt.subplots(1,2, gridspec_kw=dict(width_ratios=(1,1)))
    im = ai.imshow(img, cmap='gray', clim=(0,1))
    ai.set_title(img_title)
    ai.axis("off")
    al.imshow(render_label(lbl, img=.3*img, normalize_img=False, cmap=lbl_cmap))
    al.set_title(lbl_title)
    al.axis("off")
    plt.tight_layout()
    
def preprocess(X, Y, axis_norm=(0,1)):
    # normalize channels independently
    X = np.stack([normalize(x, 1, 99.8, axis=axis_norm) for x in tqdm(X, leave=True, desc="Normalize images")])
    # fill holes in labels
    Y = np.stack([fill_label_holes(y) for y in tqdm(Y, leave=True, desc="Fill holes in labels")])
    return X, Y


# %% [markdown] tags=[] jp-MarkdownHeadingCollapsed=true jp-MarkdownHeadingCollapsed=true
# ## Inspect the dataset

# %%
base_path = Path("data/exercise3")

# %%
x = np.stack([imread(str(p)) for p in sorted((base_path/ "images").glob("*.tif"))])
y = np.stack([imread(str(p)) for p in sorted((base_path/ "gt_tracking").glob("*.tif"))])
assert len(x) == len(x)
print(f"Number of images: {len(x)}")
print(f"Image shape: {x[0].shape}")
links = pd.read_csv(base_path / "gt_tracking" / "man_track.txt", names=["track_id", "from", "to", "parent_id"], sep=" ")
print("Links")
links[:10]

# %%
x, y = preprocess(x, y)

# %%
idx = 0
plot_img_label(x[idx], y[idx])

# %% [markdown] tags=[] jp-MarkdownHeadingCollapsed=true jp-MarkdownHeadingCollapsed=true
# ## Object detection using a pre-trained neural network

# %%
idx = 0
model = StarDist2D(None, name="stardist_breast_cancer", basedir="models")
(detections, details), (prob, _) = model.predict_instances(x[idx], scale=(1, 1), nms_thresh=0.3, prob_thresh=0.3, return_predict=True)
plot_img_label(x[idx], detections, lbl_title="detections")

# %%
coord, points, polygon_prob = details['coord'], details['points'], details['prob']
plt.figure()
plt.subplot(121)
plt.title("Predicted Polygons")
_draw_polygons(coord, points, polygon_prob, show_dist=True)
plt.imshow(x[idx], cmap='gray'); plt.axis('off')

plt.subplot(122)
plt.title("Object center probability")
plt.imshow(prob, cmap='magma'); plt.axis('off')
plt.tight_layout()
plt.show() 

# %%
prob_thres = 0.3
nms_thres = 0.6
scale = (1.0, 1.0)
pred = [model.predict_instances(xi, show_tile_progress=False, scale=scale, nms_thresh=nms_thres, prob_thresh=prob_thres, return_predict=True)
              for xi in tqdm(x)]
detections = np.array([xi[0][0] for xi in pred])
centers = [xi[0][1]["points"] for xi in pred]
center_probs = [xi[0][1]["prob"] for xi in pred]
prob_maps = np.stack([xi[1][0] for xi in pred])

# %%
np.savez(
    file=base_path / "detected.npz",
    detections=detections,
    centers=centers,
    center_probs=center_probs,
    prob_maps=prob_maps,
)

# %%
det = np.load(base_path / "detected.npz", allow_pickle=True)
links = 
detections = det["detections"]
centers = det["centers"]
center_probs = det["center_probs"]
prob_maps = det["prob_maps"]
