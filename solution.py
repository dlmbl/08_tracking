# -*- coding: utf-8 -*-
# ---
# jupyter:
#   jupytext:
#     custom_cell_magics: kql
#     formats: py:percent,ipynb
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.11.2
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Exercise 9: Tracking-by-detection with an integer linear program (ILP)
#
# Objective:
# - Write a pipeline that takes in cell detections and links them across time to obtain lineage trees
#
# Methods/Tools:
#
# - **`networkx`**: To represent the tracking inputs and outputs as graphs. Tracking is often framed
#     as a graph optimization problem. Nodes in the graph represent detections, and edges represent links
#     across time. The "tracking" task is then framed as selecting the correct edges to link your detections.
# - **`motile`**: To set up and solve an Integer Linear Program (ILP) for tracking.
#     ILP-based methods frame tracking as a constrained optimization problem. The task is to select a subset of nodes/edges from a "candidate graph" of all possible nodes/edges. The subset must minimize user-defined costs (e.g. edge distance), while also satisfying a set of tracking constraints (e.g. each cell is linked to at most one cell in the previous frame). Note: this tracking approach is not inherently using
#     "deep learning" - the costs and constraints are usually hand-crafted to encode biological and data-based priors, although cost features can also be learned from data.
# - **`napari`**: To visualize tracking inputs and outputs. Qualitative analysis is crucial for tuning the 
#     weights of the objective function and identifying data-specific costs and constraints.
# - **`traccuracy`**: To evaluate tracking results. Metrics such as accuracy can be misleading for tracking,
#     because rare events such as divisions are much harder than the common linking tasks, and might
#     be more biologically relevant for downstream analysis. Therefore, it is important to evaluate on
#     a wide range of error metrics and determine which are most important for your use case.
#
# After running through the full tracking pipeline, from loading to evaluation, we will learn how to **incorporate custom costs** based on dataset-specific prior information. As a bonus exercise, 
# you can learn how to **learn the best cost weights** for a task from
# from a small amount of ground truth tracking information.
#
# You can run this notebook on your laptop, a GPU is not needed.
#
# <div class="alert alert-danger">
# Set your python kernel to <code>09-tracking</code>
# </div>
#
# Places where you are expected to write code are marked with
# ```
# ### YOUR CODE HERE ###
# ```
#
# This notebook was originally written by Benjamin Gallusser, and was edited for 2024 by Caroline Malin-Mayor.

# %% [markdown]
# ## Import packages

# %%
# %load_ext autoreload
# %autoreload 2
# TODO: remove
import motile

# %%
import time
from pathlib import Path

import skimage
import numpy as np
import napari
import networkx as nx
import scipy


import motile

import zarr
from motile_toolbox.visualization import to_napari_tracks_layer
from motile_toolbox.candidate_graph import graph_to_nx
import motile_plugin.widgets as plugin_widgets
from motile_plugin.backend.motile_run import MotileRun
from napari.layers import Tracks
import traccuracy
from traccuracy import run_metrics
from traccuracy.metrics import CTCMetrics, DivisionMetrics
from traccuracy.matchers import IOUMatcher
from csv import DictReader

from tqdm.auto import tqdm

from typing import Iterable, Any

# %% [markdown]
# ## Load the dataset and inspect it in napari

# %% [markdown]
# For this exercise we will be working with a fluorescence microscopy time-lapse of breast cancer cells with stained nuclei (SiR-DNA). It is similar to the dataset at https://zenodo.org/record/4034976#.YwZRCJPP1qt. The raw data, pre-computed segmentations, and detection probabilities are saved in a zarr, and the ground truth tracks are saved in a csv. The segmentation was generated with a pre-trained StartDist model, so there may be some segmentation errors which can affect the tracking process. The detection probabilities also come from StarDist, and are downsampled in x and y by 2 compared to the detections and raw data.

# %% [markdown]
# Here we load the raw image data, segmentation, and probabilities from the zarr, and view them in napari.

# %%
data_path = "./data/breast_cancer_fluo.zarr"
data_root = zarr.open(data_path, 'r')
image_data = data_root["raw"][:]
segmentation = data_root["seg"][:]
probabilities = data_root["probs"][:]

# %% [markdown]
# Let's use [napari](https://napari.org/tutorials/fundamentals/getting_started.html) to visualize the data. Napari is a wonderful viewer for imaging data that you can interact with in python, even directly out of jupyter notebooks. If you've never used napari, you might want to take a few minutes to go through [this tutorial](https://napari.org/stable/tutorials/fundamentals/viewer.html).

# %%
viewer = napari.Viewer()
viewer.add_image(image_data, name="raw")
viewer.add_labels(segmentation, name="seg")
viewer.add_image(probabilities, name="probs", scale=(1, 2, 2))


# %% [markdown]
# ## Read in the ground truth graph
#
# In addition to the image data and segmentations, we also have a ground truth tracking solution.
# The ground truth tracks are stored in a CSV with five columns: id, time, x, y, and parent_id.
#
# Each row in the CSV represents a detection at location (time, x, y) with the given id.
# If the parent_id is not -1, it represents the id of the parent detection in the previous time frame.
# For cell tracking, tracks can usually be stored in this format, because there is no merging.
# With merging, a more complicated data struture would be needed.
#
# Note that there are no ground truth segmentations - each detection is just a point representing the center of a cell.
#

# %% [markdown]
#
# <div class="alert alert-block alert-info"><h3>Task 1: Read in the ground truth graph</h3>
#
# For this task, you will read in the csv and store the tracks as a <a href=https://en.wikipedia.org/wiki/Directed_graph>directed graph</a> using the `networkx` library. Take a look at the documentation for the networkx DiGraph <a href=https://networkx.org/documentation/stable/reference/classes/digraph.html>here</a> to learn how to create a graph, add nodes and edges with attributes, and access those nodes and edges.
#
# Here are the requirements for the graph:
# <ol>
#     <li>Each row in the CSV becomes a node in the graph</li>
#     <li>The node id is an integer specified by the "id" column in the csv</li>
#     <li>Each node has an integer "t" attribute specified by the "time" column in the csv</li>
#     <li>Each node has float "x", "y" attributes storing the corresponding values from the csv</li>
#     <li>If the parent_id is not -1, then there is an edge in the graph from "parent_id" to "id"</li>
# </ol>
#
# You can read the CSV using basic python file io, csv.DictReader, pandas, or any other tool you are comfortable with. If not using pandas, remember to cast your read in values from strings to integers or floats.
# </div>
#

# %% tags=["task"]
def read_gt_tracks():
    gt_tracks = nx.DiGraph()
    ### YOUR CODE HERE ###
    return gt_tracks

gt_tracks = read_gt_tracks()


# %% tags=["solution"]
def read_gt_tracks():
    gt_tracks = nx.DiGraph()
    with open("data/breast_cancer_fluo_gt_tracks.csv") as f:
        reader = DictReader(f)
        for row in reader:
            _id = int(row["id"])
            attrs = {
                "x": float(row["x"]),
                "y": float(row["y"]),
                "t": int(row["time"]),
            }
            parent_id = int(row["parent_id"])
            gt_tracks.add_node(_id, **attrs)
            if parent_id != -1:
                gt_tracks.add_edge(parent_id, _id)
    return gt_tracks

gt_tracks = read_gt_tracks()

# %%
# run this cell to test your implementation
assert gt_tracks.number_of_nodes() == 5490, f"Found {gt_tracks.number_of_nodes()} nodes, expected 5490"
assert gt_tracks.number_of_edges() == 5120, f"Found {gt_tracks.number_of_edges()} edges, expected 5120"
for node, data in gt_tracks.nodes(data=True):
    assert type(node) == int, f"Node id {node} has type {type(node)}, expected 'int'"
    assert "t" in data, f"'t' attribute missing for node {node}"
    assert type(data["t"]) == int, f"'t' attribute has type {type(data['t'])}, expected 'int'"
    assert "x" in data, f"'x' attribute missing for node {node}"
    assert type(data["x"]) == float, f"'x' attribute has type {type(data['x'])}, expected 'float'"
    assert "y" in data, f"'y' attribute missing for node {node}"
    assert type(data["y"]) == float, f"'y' attribute has type {type(daåa['y'])}, expected 'float'"
print("Your graph passed all the tests!")

# %% [markdown]
# We can also use the helper function `to_napari_tracks_layer` to visualize the ground truth tracks in our napari viewer.

# %%

widget = plugin_widgets.TreeWidget(viewer)
viewer.window.add_dock_widget(widget, name="Lineage View", area="bottom")

# %%
ground_truth_run = MotileRun(
    run_name="ground_truth",
    tracks=gt_tracks,
)

widget.view_controller.update_napari_layers(ground_truth_run, time_attr="t", pos_attr=("x", "y"))

# %% [markdown]
# ## Build a candidate graph from the detections
#
# To set up our tracking problem, we will create a "candidate graph" - a DiGraph that contains all possible detections (graph nodes) and links (graph edges) between them.
#
# Then we use an optimization method called an integer linear program (ILP) to select the best nodes and edges from the candidate graph to generate our final tracks.
#
# To create our candidate graph, we will use the provided StarDist segmentations.
# Each node in the candidate graph represents one segmentation, and each edge represents a potential link between segmentations. This candidate graph will also contain features that will be used in the optimization task, such as position on nodes and, later, customized scores on edges.


# %% [markdown]
# <div class="alert alert-block alert-info"><h3>Task 2: Extract candidate nodes from the predicted segmentations</h3>
# First we need to turn each segmentation into a node in a `networkx.DiGraph`. 
# Use <a href=https://scikit-image.org/docs/stable/api/skimage.measure.html#skimage.measure.regionprops>skimage.measure.regionprops</a> to extract properties from each segmentation, and create a candidate graph with nodes only.
#
#
# Here are the requirements for the output graph:
# <ol>
#     <li>Each detection (unique label id) in the segmentation becomes a node in the graph</li>
#     <li>The node id is the label of the detection</li>
#     <li>Each node has an integer "t" attribute, based on the index into the first dimension of the input segmentation array</li>
#     <li>Each node has float "x" and "y" attributes containing the "x" and "y" values from the centroid of the detection region</li>
#     <li>The graph has no edges (yet!)</li>
# </ol>
# </div>

# %% tags=["task"]
def nodes_from_segmentation(segmentation: np.ndarray) -> nx.DiGraph:
    """Extract candidate nodes from a segmentation. 

    Args:
        segmentation (np.ndarray): A numpy array with integer labels and dimensions
            (t, y, x).

    Returns:
        nx.DiGraph: A candidate graph with only nodes.
    """
    cand_graph = nx.DiGraph()
    print("Extracting nodes from segmentation")
    for t in tqdm(range(len(segmentation))):
        seg_frame = segmentation[t]
        props = skimage.measure.regionprops(seg_frame)
        for regionprop in props:
            ### YOUR CODE HERE ###
        
    return cand_graph

cand_graph = nodes_from_segmentation(segmentation)


# %% tags=["solution"]
def nodes_from_segmentation(segmentation: np.ndarray) -> nx.DiGraph:
    """Extract candidate nodes from a segmentation. 

    Args:
        segmentation (np.ndarray): A numpy array with integer labels and dimensions
            (t, y, x).

    Returns:
        nx.DiGraph: A candidate graph with only nodes.
    """
    cand_graph = nx.DiGraph()
    print("Extracting nodes from segmentation")
    for t in tqdm(range(len(segmentation))):
        seg_frame = segmentation[t]
        props = skimage.measure.regionprops(seg_frame)
        for regionprop in props:
            node_id = regionprop.label
            attrs = {
                "t": t,
                "x": float(regionprop.centroid[0]),
                "y": float(regionprop.centroid[1]),
            }
            assert node_id not in cand_graph.nodes
            cand_graph.add_node(node_id, **attrs)
    return cand_graph

cand_graph = nodes_from_segmentation(segmentation)

# %%
# run this cell to test your implementation of the candidate graph
assert cand_graph.number_of_nodes() == 6123, f"Found {cand_graph.number_of_nodes()} nodes, expected 6123"
assert cand_graph.number_of_edges() == 0, f"Found {cand_graph.number_of_edges()} edges, expected 0"
for node, data in cand_graph.nodes(data=True):
    assert type(node) == int, f"Node id {node} has type {type(node)}, expected 'int'"
    assert "t" in data, f"'t' attribute missing for node {node}"
    assert type(data["t"]) == int, f"'t' attribute has type {type(data['t'])}, expected 'int'"
    assert "x" in data, f"'x' attribute missing for node {node}"
    assert type(data["x"]) == float, f"'x' attribute has type {type(data['x'])}, expected 'float'"
    assert "y" in data, f"'y' attribute missing for node {node}"
    assert type(data["y"]) == float, f"'y' attribute has type {type(daåa['y'])}, expected 'float'"
print("Your candidate graph passed all the tests!")

# %% [markdown]
# We can visualize our candidate points using the napari Points layer. You should see one point in the center of each segmentation when we display it using the below cell.

# %%
points_array = np.array([[data["t"], data["x"], data["y"]] for node, data in cand_graph.nodes(data=True)])
cand_points_layer = napari.layers.Points(data=points_array, name="cand_points")
viewer.add_layer(cand_points_layer)


# %% [markdown]
# ### Adding Candidate Edges
#
# After extracting the nodes, we need to add candidate edges. The `add_cand_edges` function below adds candidate edges to a nodes-only graph by connecting all nodes in adjacent frames that are closer than a given max_edge_distance.
#
# Note: At the bottom of the cell, we add edges to our candidate graph with max_edge_distance=50. This is the maximum number of pixels that a cell centroid will be able to move between frames. If you want longer edges to be possible, you can increase this distance, but solving may take longer.

# %%
def _compute_node_frame_dict(cand_graph: nx.DiGraph) -> dict[int, list[Any]]:
    """Compute dictionary from time frames to node ids for candidate graph.

    Args:
        cand_graph (nx.DiGraph): A networkx graph

    Returns:
        dict[int, list[Any]]: A mapping from time frames to lists of node ids.
    """
    node_frame_dict: dict[int, list[Any]] = {}
    for node, data in cand_graph.nodes(data=True):
        t = data["t"]
        if t not in node_frame_dict:
            node_frame_dict[t] = []
        node_frame_dict[t].append(node)
    return node_frame_dict

def create_kdtree(cand_graph: nx.DiGraph, node_ids: Iterable[Any]) -> scipy.spatial.KDTree:
    positions = [[cand_graph.nodes[node]["x"], cand_graph.nodes[node]["y"]] for node in node_ids]
    return scipy.spatial.KDTree(positions)

def add_cand_edges(
    cand_graph: nx.DiGraph,
    max_edge_distance: float,
) -> None:
    """Add candidate edges to a candidate graph by connecting all nodes in adjacent
    frames that are closer than max_edge_distance. Also adds attributes to the edges.

    Args:
        cand_graph (nx.DiGraph): Candidate graph with only nodes populated. Will
            be modified in-place to add edges.
        max_edge_distance (float): Maximum distance that objects can travel between
            frames. All nodes within this distance in adjacent frames will by connected
            with a candidate edge.
        node_frame_dict (dict[int, list[Any]] | None, optional): A mapping from frames
            to node ids. If not provided, it will be computed from cand_graph. Defaults
            to None.
    """
    print("Extracting candidate edges")
    node_frame_dict = _compute_node_frame_dict(cand_graph)

    frames = sorted(node_frame_dict.keys())
    prev_node_ids = node_frame_dict[frames[0]]
    prev_kdtree = create_kdtree(cand_graph, prev_node_ids)
    for frame in tqdm(frames):
        if frame + 1 not in node_frame_dict:
            continue
        next_node_ids = node_frame_dict[frame + 1]
        next_kdtree = create_kdtree(cand_graph, next_node_ids)

        matched_indices = prev_kdtree.query_ball_tree(next_kdtree, max_edge_distance)

        for prev_node_id, next_node_indices in zip(prev_node_ids, matched_indices):
            for next_node_index in next_node_indices:
                next_node_id = next_node_ids[next_node_index]
                cand_graph.add_edge(prev_node_id, next_node_id)

        prev_node_ids = next_node_ids
        prev_kdtree = next_kdtree

add_cand_edges(cand_graph, max_edge_distance=50)

# %% [markdown]
# Visualizing the candidate edges in napari is, unfortunately, not yet possible. However, we can print out the number of candidate nodes and edges, and compare it to the ground truth nodes and edgesedges. We should see that we have a few more candidate nodes than ground truth (due to false positive detections) and many more candidate edges than ground truth - our next step will be to use optimization to pick a subset of the candidate nodes and edges to generate our solution tracks.

# %%
print(f"Our candidate graph has {cand_graph.number_of_nodes()} nodes and {cand_graph.number_of_edges()} edges")
print(f"Our ground truth track graph has {gt_tracks.number_of_nodes()} nodes and {gt_tracks.number_of_edges()}")


# %% [markdown]
# ## Checkpoint 1
# <div class="alert alert-block alert-success"><h3>Checkpoint 1: We have visualized our data in napari and set up a candidate graph with all possible detections and links that we could select with our optimization task. </h3>
#
# We will now together go through the `motile` <a href=https://funkelab.github.io/motile/quickstart.html#sec-quickstart>quickstart</a> example before you actually set up and run your own motile optimization. If you reach this checkpoint early, feel free to start reading through the quickstart and think of questions you want to ask!
# </div>

# %% [markdown]
# ## Setting Up the Tracking Optimization Problem

# %% [markdown]
# As hinted earlier, our goal is to prune the candidate graph. More formally we want to find a graph $\tilde{G}=(\tilde{V}, \tilde{E})$ whose vertices $\tilde{V}$ are a subset of the candidate graph vertices $V$ and whose edges $\tilde{E}$ are a subset of the candidate graph edges $E$.
#
#
# Finding a good subgraph $\tilde{G}=(\tilde{V}, \tilde{E})$ can be formulated as an [integer linear program (ILP)](https://en.wikipedia.org/wiki/Integer_programming) (also, refer to the tracking lecture slides), where we assign a binary variable $x$ and a cost $c$ to each vertex and edge in $G$, and then computing $min_x c^Tx$.
#
# A set of linear constraints ensures that the solution will be a feasible cell tracking graph. For example, if an edge is part of $\tilde{G}$, both its incident nodes have to be part of $\tilde{G}$ as well.
#
# `motile` ([docs here](https://funkelab.github.io/motile/)), makes it easy to link with an ILP in python by implementing common linking constraints and costs. 
#
# TODO: delete this?

# %% [markdown]
# ## Task 3 - Basic tracking with motile
# <div class="alert alert-block alert-info"><h3>Task 3: Set up a basic motile tracking pipeline</h3>
# <p>Use the motile <a href=https://funkelab.github.io/motile/quickstart.html#sec-quickstart>quickstart</a> example to set up a basic motile pipeline for our task. 
#
# Here are some key similarities and differences between the quickstart and our task:
# <ul>
#     <li>We do not have scores on our nodes. This means we do not need to include a `NodeSelection` cost.</li>
#     <li>We also do not have scores on our edges. However, we can use the edge distance as a cost, so that longer edges are more costly than shorter edges. Instead of using the `EdgeSelection` cost, we can use the <a href=https://funkelab.github.io/motile/api.html#edgedistance>`EdgeDistance`</a> cost with `position_attribute="pos"`. You will want a positive weight, since higher distances should be more costly, unlike in the example when higher scores were good and so we inverted them with a negative weight.</li>
#     <li>Because distance is always positive, and you want a positive weight, you will want to include a negative constant on the `EdgeDistance` cost. If there are no negative selection costs, the ILP will always select nothing, because the cost of selecting nothing is zero.</li>
#     <li>We want to allow divisions. So, we should pass in 2 to our `MaxChildren` constraint. The `MaxParents` constraint should have 1, the same as the quickstart, because neither task allows merging.</li>
#     <li>You should include an Appear cost similar to the one in the quickstart.</li>
# </ul>
#
# Once you have set up the basic motile optimization task in the function below, you will probably need to adjust the weight and constant values on your costs until you get a solution that looks reasonable.
#
# </p>
# </div>
#

# %% tags=["task"]
def solve_basic_optimization(cand_graph):
    """Set up and solve the network flow problem.

    Args:
        graph (motile.TrackGraph): The candidate graph.

    Returns:
        nx.DiGraph: The networkx digraph with the selected solution tracks
    """

    cand_trackgraph = motile.TrackGraph(cand_graph, frame_attribute="t")
    solver = motile.Solver(cand_trackgraph)
    ### YOUR CODE HERE ###
    solver.solve()
    solution_graph = graph_to_nx(solver.get_selected_subgraph())
    return solution_graph


# %% tags=["solution"]
def solve_basic_optimization(cand_graph):
    """Set up and solve the network flow problem.

    Args:
        graph (nx.DiGraph): The candidate graph.

    Returns:
        nx.DiGraph: The networkx digraph with the selected solution tracks
    """
    cand_trackgraph = motile.TrackGraph(cand_graph, frame_attribute="t")
    solver = motile.Solver(cand_trackgraph)

    solver.add_cost(
        motile.costs.EdgeDistance(weight=1, constant=-20, position_attribute=("x", "y"))
    )
    solver.add_cost(motile.costs.Appear(constant=1.0))

    solver.add_constraint(motile.constraints.MaxParents(1))
    solver.add_constraint(motile.constraints.MaxChildren(2))

    solver.solve()
    solution_graph = graph_to_nx(solver.get_selected_subgraph())
    return solution_graph


# %% [markdown]
# Here is a utility function to gauge some statistics of a solution.

# %%
def print_graph_stats(graph, name):
    print(f"{name}\t\t{graph.number_of_nodes()} nodes\t{graph.number_of_edges()} edges\t{len(list(nx.weakly_connected_components(graph)))} tracks")


# %% [markdown]
# Here we actually run the optimization, and compare the found solution to the ground truth.
#
# <div class="alert alert-block alert-warning"><h3>Gurobi license error</h3>
# Please ignore the warning `Could not create Gurobi backend ...`.
#
#
# Our integer linear program (ILP) tries to use the proprietary solver Gurobi. You probably don't have a license, in which case the ILP will fall back to the open source solver SCIP.
# </div>

# %%
# run this cell to actually run the solving and get a solution
solution_graph = solve_basic_optimization(cand_graph)

# then print some statistics about the solution compared to the ground truth
print_graph_stats(solution_graph, "solution")
print_graph_stats(gt_tracks, "gt tracks")



# %% [markdown]
# If you haven't selected any nodes or edges in your solution, try adjusting your weight and/or constant values. Make sure you have some negative costs or selecting nothing will always be the best solution!

# %% [markdown]
# <div class="alert alert-block alert-warning"><h3>Question 1: Interpret your results based on statistics</h3>
# <p>
# What do these printed statistics tell you about your solution? What else would you like to know?
# </p>
# </div>

# %% [markdown]
# ## Visualize the Result
# Rather than just looking at printed statistics about our solution, let's visualize it in `napari`.
#
# This involves two steps:
# 1. First, we can add a tracks layer with the solution graph.
# 2. Second, we can add another segmentation layer, where the segmentations are relabeled so that the same cell will be the same color over time. Cells will still change color at division.
#
# Note that bad tracking results at this point does not mean that you implemented anything wrong! We still need to customize our costs and constraints to the task before we can get good results. As long as your pipeline selects something, and you can kind of interepret why it is going wrong, that is all that is needed at this point.

# %%
# recolor the segmentation

from motile_toolbox.visualization.napari_utils import assign_tracklet_ids
def relabel_segmentation(
    solution_nx_graph: nx.DiGraph,
    segmentation: np.ndarray,
) -> np.ndarray:
    """Relabel a segmentation based on tracking results so that nodes in same
    track share the same id. IDs do change at division.

    Args:
        solution_nx_graph (nx.DiGraph): Networkx graph with the solution to use
            for relabeling. Nodes not in graph will be removed from seg. Original
            segmentation ids and hypothesis ids have to be stored in the graph so we
            can map them back.
        segmentation (np.ndarray): Original (potentially multi-hypothesis)
            segmentation with dimensions (t,h,[z],y,x), where h is 1 for single
            input segmentation.

    Returns:
        np.ndarray: Relabeled segmentation array where nodes in same track share same
            id with shape (t,1,[z],y,x)
    """
    assign_tracklet_ids(solution_nx_graph)
    tracked_masks = np.zeros_like(segmentation)
    for node, data in solution_nx_graph.nodes(data=True):
        time_frame = solution_nx_graph.nodes[node]["t"]
        previous_seg_id = node
        track_id = solution_nx_graph.nodes[node]["tracklet_id"]
        previous_seg_mask = (
            segmentation[time_frame] == previous_seg_id
        )
        tracked_masks[time_frame][previous_seg_mask] = track_id
    return tracked_masks

solution_seg = relabel_segmentation(solution_graph, segmentation)

# %%
basic_run = MotileRun(
    run_name="basic_solution_test",
    tracks=solution_graph,
    output_segmentation=np.expand_dims(solution_seg, axis=1)  # need to add a dummy dimension to fit API
)

widget.view_controller.update_napari_layers(basic_run, time_attr="t", pos_attr=("x", "y"))

# %% [markdown]
# <div class="alert alert-block alert-warning"><h3>Question 2: Interpret your results based on visualization</h3>
# <p>
# How is your solution based on looking at the visualization? When is it doing well? When is it doing poorly?
# </p>
# </div>
#

# %% [markdown]
# ## Evaluation Metrics
#
# We were able to understand via visualizing the predicted tracks on the images that the basic solution is far from perfect for this problem.
#
# Additionally, we would also like to quantify this. We will use the package [`traccuracy`](https://traccuracy.readthedocs.io/en/latest/) to calculate some [standard metrics for cell tracking](http://celltrackingchallenge.net/evaluation-methodology/). For example, a high-level indicator for tracking performance is called TRA.
#
# If you're interested in more detailed metrics, you can look at the false positive (FP) and false negative (FN) nodes, edges and division events.


# %%

from skimage.draw import disk
def make_gt_detections(data_shape, gt_tracks, radius):
    segmentation = np.zeros(data_shape, dtype="uint32")
    frame_shape = data_shape[1:]
    # make frame with one cell in center with label 1
    for node, data in gt_tracks.nodes(data=True):
        pos = (data["x"], data["y"])
        time = data["t"]
        gt_tracks.nodes[node]["label"] = node
        rr, cc = disk(center=pos, radius=radius, shape=frame_shape)
        segmentation[time][rr, cc] = node
    return segmentation

gt_dets = make_gt_detections(data_root["raw"].shape, gt_tracks, 10)
# viewer.add_image(gt_dets)


# %%
def get_metrics(gt_graph, labels, pred_graph, pred_segmentation):
    """Calculate metrics for linked tracks by comparing to ground truth.

    Args:
        gt_graph (networkx.DiGraph): Ground truth graph.
        labels (np.ndarray): Ground truth detections.
        pred_graph (networkx.DiGraph): Predicted graph.
        pred_segmentation (np.ndarray): Predicted dense segmentation.

    Returns:
        results (dict): Dictionary of metric results.
    """

    gt_graph = traccuracy.TrackingGraph(
        graph=gt_graph,
        frame_key="t",
        label_key="label",
        location_keys=("x", "y"),
        segmentation=labels,
    )

    pred_graph = traccuracy.TrackingGraph(
        graph=pred_graph,
        frame_key="t",
        label_key="tracklet_id",
        location_keys=("x", "y"),
        segmentation=pred_segmentation,
    )

    results = run_metrics(
        gt_data=gt_graph,
        pred_data=pred_graph,
        matcher=IOUMatcher(iou_threshold=0.3, one_to_one=True),
        metrics=[CTCMetrics(), DivisionMetrics()],
    )

    return results


# %%
get_metrics(gt_tracks, gt_dets, solution_graph, solution_seg.astype(np.uint32))


# %% [markdown]
# <div class="alert alert-block alert-warning"><h3>Question 3: Interpret your results based on metrics</h3>
# <p>
# What additional information, if any, do the metrics give you compared to the statistics and the visualization?
# </p>
# </div>
#

# %% [markdown]
# <div class="alert alert-block alert-success"><h2>Checkpoint 2</h2>
# We have set up and run a basic ILP to get tracks and visualized and evaluated the output.  
#
# We will go over the code and discuss the answers to Questions 1, 2, and 3 together soon. If you have extra time, think about what kinds of improvements you could make to the costs and constraints to fix the issues that you are seeing. You can even try tuning your weights and constants, or adding or removing motile Costs and Constraints, and seeing how that changes the output.
# </div>

# %% [markdown]
# ## Customizing the Tracking Task
#
# There 3 main ways to encode prior knowledge about your task into the motile tracking pipeline.
# 1. Add an attribute to the candidate graph and incorporate it with an existing cost
# 2. Change the structure of the candidate graph
# 3. Add a new type of cost or constraint
#
# The first way is the most common, and is quite flexible, so we will focus on two examples of this type of customization.

# %% [markdown]
# ## Task 4 - Add an appear cost, but not at the boundary
# The Appear cost penalizes starting a new track, encouraging continuous tracks. However, you do not want to penalize tracks that appear in the first frame. In our case, we probably also do not want to penalize appearing at the "bottom" of the dataset. The built in Appear cost ([docs here](https://funkelab.github.io/motile/api.html#motile.costs.Appear_)) has an `ignore_attribute` argument, where if the node has that attribute and it evaluates to True, the Appear cost will not be paid for that node.

# %% [markdown]
#
# <div class="alert alert-block alert-info"><h3>Task 4a: Add an ignore_appear attribute to the candidate graph </h3>
# <p> 
# For each node on our candidate graph, you should add an attribute `ignore_appear` that evaluates to True if the appear cost should NOT be paid for that node. For nodes that should pay the appear cost, you can either set the attribute to False, or not add the attribute. Nodes should NOT pay the appear cost if they are in the first time frame, or if they are within a certain distance to the "bottom" of the dataset. (You will need to determine the coordinate range that you consider the "bottom" of the dataset, perhaps by hovering over the napari image layer and seeing what the coordinate values are).
# </p>
# </div>

# %% tags=["task"]
def add_appear_ignore_attr(cand_graph):
    for node in cand_graph.nodes():
        ### YOUR CODE HERE ###
        pass  # delete this

add_appear_ignore_attr(cand_graph)


# %% tags=["solution"]
def add_appear_ignore_attr(cand_graph):
    for node in cand_graph.nodes():
        time = cand_graph.nodes[node]["t"]
        pos_x = cand_graph.nodes[node]["x"]
        if time == 0 or pos_x >= 710:
            cand_graph.nodes[node]["ignore_appear"] = True

add_appear_ignore_attr(cand_graph)


# %% [markdown]
# <div class="alert alert-block alert-info"><h3>Task 4b: Use the `ignore_appear` attribute in your solver pipeline </h3>
# <p>Copy your solver pipeline from above, and then adapt the Appear cost to use our new `ignore_appear` attribute. You may also want to adapt the Appear constant value. Then re-solve to see if performance improves.
# </p>
# </div>

# %% tags=["task"]
def solve_appear_optimization(cand_graph):
    """Set up and solve the network flow problem.

    Args:
        graph (nx.DiGraph): The candidate graph.

    Returns:
        nx.DiGraph: The networkx digraph with the selected solution tracks
    """

    cand_trackgraph = motile.TrackGraph(cand_graph, frame_attribute="t")
    solver = motile.Solver(cand_trackgraph)

    ### YOUR CODE HERE ###

    solver.solve()
    solution_graph = graph_to_nx(solver.get_selected_subgraph())
    return solution_graph


# %% tags=["solution"]
def solve_appear_optimization(cand_graph):
    """Set up and solve the network flow problem.

    Args:
        graph (nx.DiGraph): The candidate graph.

    Returns:
        nx.DiGraph: The networkx digraph with the selected solution tracks
    """

    cand_trackgraph = motile.TrackGraph(cand_graph, frame_attribute="t")
    solver = motile.Solver(cand_trackgraph)

    solver.add_cost(
        motile.costs.EdgeDistance(weight=1, constant=-20, position_attribute=("x", "y"))
    )
    solver.add_cost(motile.costs.Appear(constant=10, ignore_attribute="ignore_appear"))

    solver.add_constraint(motile.constraints.MaxParents(1))
    solver.add_constraint(motile.constraints.MaxChildren(2))

    solver.solve()
    solution_graph = graph_to_nx(solver.get_selected_subgraph())
    return solution_graph


# %%
solution_graph = solve_appear_optimization(cand_graph)
solution_seg = relabel_segmentation(solution_graph, segmentation)

# %%
appear_run = MotileRun(
    run_name="appear_solution",
    tracks=solution_graph,
    output_segmentation=np.expand_dims(solution_seg, axis=1)  # need to add a dummy dimension to fit API
)

widget.view_controller.update_napari_layers(appear_run, time_attr="t", pos_attr=("x", "y"))


# %%
get_metrics(gt_tracks, gt_dets, solution_graph, solution_seg)

# %% [markdown]
# ## Task 5 - Incorporating Known Direction of Motion
#
# So far, we have been using motile's EdgeDistance as an edge selection cost, which penalizes longer edges by computing the Euclidean distance between the endpoints. However, in our dataset we see a trend of upward motion in the cells, and the false detections at the top are not moving. If we penalize movement based on what we expect, rather than Euclidean distance, we can select more correct cells and penalize the non-moving artefacts at the same time.
#  
#

# %% [markdown]
# <div class="alert alert-block alert-info"><h3>Task 5a: Add a drift distance attribute</h3>
# <p> For this task, we need to determine the "expected" amount of motion, then add an attribute to our candidate edges that represents distance from the expected motion direction.</p>
# </div>

# %% tags=["task"]
drift = ... ### YOUR CODE HERE ###

def add_drift_dist_attr(cand_graph, drift):
    for edge in cand_graph.edges():
        ### YOUR CODE HERE ###
        # get the location of the endpoints of the edge
        # then compute the distance between the expected movement and the actual movement
        # and save it in the "drift_dist" attribute (below)
        cand_graph.edges[edge]["drift_dist"] = drift_dist

add_drift_dist_attr(cand_graph, drift)

# %% tags=["solution"]
drift = np.array([-10, 0])

def add_drift_dist_attr(cand_graph, drift):
    for edge in cand_graph.edges():
        source, target = edge
        source_data = cand_graph.nodes[source]
        source_pos = np.array([source_data["x"], source_data["y"]])
        target_data = cand_graph.nodes[target]
        target_pos = np.array([target_data["x"], target_data["y"]])
        expected_target_pos = source_pos + drift
        drift_dist = np.linalg.norm(expected_target_pos - target_pos)
        cand_graph.edges[edge]["drift_dist"] = drift_dist

add_drift_dist_attr(cand_graph, drift)


# %% [markdown]
# <div class="alert alert-block alert-info"><h3>Task 5b: Add a drift distance attribute</h3>
# <p> Now, we set up yet another solving pipeline. This time, we will replace our EdgeDistance
# cost with an EdgeSelection cost using our new "drift_dist" attribute. The weight should be positive, since a higher distance from the expected drift should cost more, similar to our prior EdgeDistance cost. Also similarly, we need a negative constant to make sure that the overall cost of selecting tracks is negative.</p>
# </div>

# %%
def solve_drift_optimization(cand_graph):
    """Set up and solve the network flow problem.

    Args:
        cand_graph (nx.DiGraph): The candidate graph.

    Returns:
        nx.DiGraph: The networkx digraph with the selected solution tracks
    """
    cand_trackgraph = motile.TrackGraph(cand_graph, frame_attribute="t")
    solver = motile.Solver(cand_trackgraph)

    ### YOUR CODE HERE ###

    solver.solve()

    solution_graph = graph_to_nx(solver.get_selected_subgraph())
    return solution_graph

solution_graph = solve_drift_optimization(cand_graph)


# %% tags=["solution"]
def solve_drift_optimization(cand_graph):
    """Set up and solve the network flow problem.

    Args:
        cand_graph (nx.DiGraph): The candidate graph.

    Returns:
        nx.DiGraph: The networkx digraph with the selected solution tracks
    """

    cand_trackgraph = motile.TrackGraph(cand_graph, frame_attribute="t")
    solver = motile.Solver(cand_trackgraph)

    solver.add_cost(
        motile.costs.EdgeSelection(weight=1.0, constant=-30, attribute="drift_dist")
    )
    solver.add_cost(motile.costs.Appear(constant=100, ignore_attribute="ignore_appear"))
    solver.add_cost(motile.costs.Split(constant=20))

    solver.add_constraint(motile.constraints.MaxParents(1))
    solver.add_constraint(motile.constraints.MaxChildren(2))

    solver.solve()
    solution_graph = graph_to_nx(solver.get_selected_subgraph())
    return solution_graph


# %%
solution_graph = solve_drift_optimization(cand_graph)
solution_seg = relabel_segmentation(solution_graph, segmentation)

# %%
drift_run = MotileRun(
    run_name="drift_solution",
    tracks=solution_graph,
    output_segmentation=np.expand_dims(solution_seg, axis=1)  # need to add a dummy dimension to fit API
)

widget.view_controller.update_napari_layers(drift_run, time_attr="t", pos_attr=("x", "y"))

# %%
get_metrics(gt_tracks, gt_dets, solution_graph, solution_seg)


# %% [markdown]
# ## Checkpoint 4
# <div class="alert alert-block alert-success"><h3>Checkpoint 4</h3>
# That is the end of the main exercise! If you have extra time, feel free to go onto the below bonus exercise to see how to learn the weights of your costs instead of setting them manually.
# </div>

# %% [markdown]
# ## Bonus: Learning the Weights

# %% [markdown]
#

# %%
def get_cand_id(gt_node, gt_track, cand_segmentation):
    data = gt_track.nodes[gt_node]
    return cand_segmentation[data["t"], int(data["x"])][int(data["y"])]

def add_gt_annotations(gt_tracks, cand_graph, segmentation):
    for gt_node in gt_tracks.nodes():
        cand_id = get_cand_id(gt_node, gt_tracks, segmentation)
        if cand_id != 0:
            if cand_id in cand_graph:
                cand_graph.nodes[cand_id]["gt"] = True
                gt_succs = gt_tracks.successors(gt_node)
                gt_succ_matches = [get_cand_id(gt_succ, gt_tracks, segmentation) for gt_succ in gt_succs]
                cand_succs = cand_graph.successors(cand_id)
                for succ in cand_succs:
                    if succ in gt_succ_matches:
                        cand_graph.edges[(cand_id, succ)]["gt"] = True
                    else:
                        cand_graph.edges[(cand_id, succ)]["gt"] = False
    for node in cand_graph.nodes():
       if "gt" not in cand_graph.nodes[node]:
           cand_graph.nodes[node]["gt"] = False


# %%
validation_times = [0, 3]
validation_nodes = [node for node, data in cand_graph.nodes(data=True) 
                        if (data["t"] >= validation_times[0] and data["t"] < validation_times[1])]
print(len(validation_nodes))
validation_graph = cand_graph.subgraph(validation_nodes).copy()
add_gt_annotations(gt_tracks, validation_graph, segmentation)


# %%
gt_pos_nodes = [node_id for node_id, data in validation_graph.nodes(data=True) if "gt" in data and data["gt"] is True]
gt_neg_nodes = [node_id for node_id, data in validation_graph.nodes(data=True) if "gt" in data and data["gt"] is False]
gt_pos_edges = [(source, target) for source, target, data in validation_graph.edges(data=True) if "gt" in data and data["gt"] is True]
gt_neg_edges = [(source, target) for source, target, data in validation_graph.edges(data=True) if "gt" in data and data["gt"] is False]

print(f"{len(gt_pos_nodes) + len(gt_neg_nodes)} annotated: {len(gt_pos_nodes)} True, {len(gt_neg_nodes)} False")
print(f"{len(gt_pos_edges) + len(gt_neg_edges)} annotated: {len(gt_pos_edges)} True, {len(gt_neg_edges)} False")

# %%
import logging

logging.basicConfig(level=logging.INFO)

def get_ssvm_solver(cand_graph):

    cand_trackgraph = motile.TrackGraph(cand_graph, frame_attribute="t")
    solver = motile.Solver(cand_trackgraph)

    solver.add_cost(
        motile.costs.EdgeSelection(weight=1.0, constant=-30, attribute="drift_dist")
    )
    solver.add_cost(motile.costs.Appear(constant=20, ignore_attribute="ignore_appear"))
    solver.add_cost(motile.costs.Split(constant=20))

    solver.add_constraint(motile.constraints.MaxParents(1))
    solver.add_constraint(motile.constraints.MaxChildren(2))
    return solver


# %%
ssvm_solver = get_ssvm_solver(validation_graph)
ssvm_solver.fit_weights(gt_attribute="gt", regularizer_weight=100, max_iterations=50)
optimal_weights = ssvm_solver.weights
optimal_weights


# %%
def get_ssvm_solution(cand_graph, solver_weights):
    solver = get_ssvm_solver(cand_graph)
    solver.weights = solver_weights
    solver.solve()
    solution_graph = graph_to_nx(solver.get_selected_subgraph())
    return solution_graph

solution_graph = get_ssvm_solution(cand_graph, optimal_weights)
    

# %%
solution_seg = relabel_segmentation(solution_graph, segmentation)
get_metrics(gt_tracks, gt_dets, solution_graph, solution_seg)

# %%
ssvm_run = MotileRun(
    run_name="ssvm_solution",
    tracks=solution_graph,
    output_segmentation=np.expand_dims(solution_seg, axis=1)  # need to add a dummy dimension to fit API
)

widget.view_controller.update_napari_layers(ssvm_run, time_attr="t", pos_attr=("x", "y"))

# %%

# %%
