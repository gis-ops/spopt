from .BaseClass import BaseSpOptHeuristicSolver
from .base import (w_to_g, move_ok, ok_moves, region_neighbors, _centroid,
                   _closest, _seeds, is_neighbor)

import matplotlib.pyplot as plt
from scipy.spatial.distance import pdist, squareform
import pandas as pd
import geopandas as gp
import time
import numpy as np
from copy import deepcopy
from scipy.sparse.csgraph import connected_components

ITERCONSTRUCT=999
ITERSA=10



def maxp(gdf, w, attrs_name, threshold_name, threshold, top_n, max_iterations_construction=ITERCONSTRUCT,
         max_iterations_sa=ITERSA, verbose=True):
    """
    Arguments
    ---------
    gdf: geodataframe

    w: pysal W

    attrs_name: list of strings for attribute names (cols of gdf)

    threshold_name: string (name of threshold variable)

    threshold: numeric
             value for threshold

    top_n: int
           Max number of candidate regions for enclave assignment

    max_iterations_construction: int
           max number of iterations for construction phase

    max_iterations_SA: int
           max number of iterations for customized simulated annealing

    verbose: boolean
             True

    Returns
    -------

    max_p: int
           number of regions

    labels: array
           region ids for observations
    """

    attr = gdf[attrs_name].values
    threshold_array = gdf[threshold_name].values
    distance_matrix = squareform(pdist(attr, metric='cityblock'))
    n,k = attr.shape
    arr = np.arange(n)
    max_p, rl_list = construction_phase(arr, attr, threshold_array,
                                       distance_matrix, w, threshold, top_n,
                                       max_iterations_construction)

    if verbose:
        print("max_p: ", max_p)
        print('number of good partitions:', len(rl_list))



    alpha = 0.998
    tabuLength = 10
    max_no_move = attr.size
    best_obj_value = np.inf
    best_label = None
    best_fn = None
    best_sa_time = np.inf
    for irl, rl in enumerate(rl_list):
        label, regionList, regionSpatialAttr = rl
        if verbose:
            print(irl)
        for saiter in range(max_iterations_sa):
            sa_start_time = time.time()
            finalLabel, finalRegionList, finalRegionSpatialAttr = performSA(
                label, regionList, regionSpatialAttr, threshold_array,
                w, distance_matrix, threshold, alpha, tabuLength, max_no_move)
            sa_end_time = time.time()
            totalWithinRegionDistance = calculateWithinRegionDistance(
                finalRegionList, distance_matrix)
            if verbose:
                print("totalWithinRegionDistance after SA: ")
                print(totalWithinRegionDistance)
            if totalWithinRegionDistance < best_obj_value:
                best_obj_value = totalWithinRegionDistance
                best_label = finalLabel
                best_fn = irl
                best_sa_time = sa_end_time - sa_start_time
    if verbose:
        print("best objective value:")
        print(best_obj_value)

    return  max_p, best_label

def construction_phase(arr,
                       attr,
                       threshold_array,
                       distance_matrix,
                       weight,
                       spatialThre,
                       random_assign_choice,
                       max_it=999):
    labels_list = []
    pv_list = []
    max_p = 0
    maxp_labels = None
    maxp_regionList = None
    maxp_regionSpatialAttr = None

    for _ in range(max_it):
        labels = [0] * len(threshold_array)
        C = 0
        regionSpatialAttr = {}
        enclave = []
        regionList = {}
        np.random.shuffle(arr)

        labeledID = []

        for arr_index in range(0, len(threshold_array)):

            P = arr[arr_index]
            if not (labels[P] == 0):
                continue

            NeighborPolys = deepcopy(weight.neighbors[P])

            if len(NeighborPolys) < 0:
                labels[P] = -1
            else:
                C += 1
                labeledID, spatialAttrTotal = growClusterForPoly(
                    labels, threshold_array, P, NeighborPolys, C,
                    weight, spatialThre)

                if spatialAttrTotal < spatialThre:
                    enclave.extend(labeledID)
                else:
                    regionList[C] = labeledID
                    regionSpatialAttr[C] = spatialAttrTotal
        num_regions = len(regionList)

        for i, l in enumerate(labels):
            if l == -1:
                enclave.append(i)

        if num_regions < max_p:
            continue
        else:
            max_p = num_regions
            maxp_labels, maxp_regionList, maxp_regionSpatialAttr = assignEnclave(
                enclave,
                labels,
                regionList,
                regionSpatialAttr,
                threshold_array,
                weight,
                distance_matrix,
                random_assign=random_assign_choice)
            pv_list.append(max_p)
            labels_list.append(
                [maxp_labels, maxp_regionList, maxp_regionSpatialAttr])
    realLabelsList = []
    realmaxpv = max(pv_list)
    for ipv, pv in enumerate(pv_list):
        if pv == realmaxpv:
            realLabelsList.append(labels_list[ipv])

    return realmaxpv, realLabelsList


def growClusterForPoly(labels, threshold_array, P, NeighborPolys, C,
                       weight, spatialThre):
    labels[P] = C
    labeledID = [P]
    spatialAttrTotal = threshold_array[P]

    i = 0

    while i < len(NeighborPolys):

        if spatialAttrTotal >= spatialThre:
            break
        Pn = NeighborPolys[i]

        if labels[Pn] == 0:
            labels[Pn] = C
            labeledID.append(Pn)
            spatialAttrTotal += threshold_array[Pn]
            if spatialAttrTotal < spatialThre:
                PnNeighborPolys = weight.neighbors[Pn]
                for pnn in PnNeighborPolys:
                    if not pnn in NeighborPolys:
                        NeighborPolys.append(pnn)
        i += 1
    return labeledID, spatialAttrTotal


def assignEnclave(enclave,
                  labels,
                  regionList,
                  regionSpatialAttr,
                  threshold_array,
                  weight,
                  distance_matrix,
                  random_assign=1):
    enclave_index = 0
    while len(enclave) > 0:
        ec = enclave[enclave_index]
        ecNeighbors = weight.neighbors[ec]
        minDistance = np.Inf
        assignedRegion = 0
        ecNeighborsList = []
        ecTopNeighborsList = []

        for ecn in ecNeighbors:
            if ecn in enclave:
                continue
            rm = np.array(regionList[labels[ecn]])
            totalDistance = distance_matrix[ec, rm].sum()
            ecNeighborsList.append((ecn, totalDistance))
        ecNeighborsList = sorted(ecNeighborsList, key=lambda tup: tup[1])
        top_num = min([len(ecNeighborsList), random_assign])
        if top_num > 0:
            ecn_index = np.random.randint(top_num)
            assignedRegion = labels[ecNeighborsList[ecn_index][0]]

        if assignedRegion == 0:
            enclave_index += 1
        else:
            labels[ec] = assignedRegion
            regionList[assignedRegion].append(ec)
            regionSpatialAttr[assignedRegion] += threshold_array[ec]
            del enclave[enclave_index]
            enclave_index = 0
    return [
        deepcopy(labels),
        deepcopy(regionList),
        deepcopy(regionSpatialAttr)
    ]


def calculateWithinRegionDistance(regionList, distance_matrix):
    totalWithinRegionDistance = 0
    for k, v in regionList.items():
        nv = np.array(v)
        regionDistance = distance_matrix[nv, :][:, nv].sum() / 2
        totalWithinRegionDistance += regionDistance

    return totalWithinRegionDistance


def pickMoveArea(labels, regionLists, regionSpatialAttrs,
                 threshold_array, weight, distance_matrix, threshold):
    potentialAreas = []
    labels_array = np.array(labels)
    for k, v in regionSpatialAttrs.items():
        rla = np.array(regionLists[k])
        rasa = threshold_array[rla]
        lostSA = v - rasa
        pas_indices = np.where(lostSA > threshold)[0]
        if pas_indices.size > 0:
            for pasi in pas_indices:
                leftAreas = np.delete(rla, pasi)
                ws = weight.sparse
                cc = connected_components(ws[leftAreas, :][:, leftAreas])
                if cc[0] == 1:
                    potentialAreas.append(rla[pasi])
        else:
            continue

    return potentialAreas


def checkMove(poa, labels, regionLists, threshold_array, weight,
              distance_matrix, threshold):
    poaNeighbor = weight.neighbors[poa]
    donorRegion = labels[poa]

    rm = np.array(regionLists[donorRegion])
    lostDistance = distance_matrix[poa, rm].sum()
    potentialMove = None

    minAddedDistance = np.Inf
    for poan in poaNeighbor:
        recipientRegion = labels[poan]
        if donorRegion != recipientRegion:
            rm = np.array(regionLists[recipientRegion])
            addedDistance = distance_matrix[poa, rm].sum()

            if addedDistance < minAddedDistance:
                minAddedDistance = addedDistance
                potentialMove = (poa, donorRegion, recipientRegion)

    return [lostDistance, minAddedDistance, potentialMove]


def performSA(initLabels, initRegionList, initRegionSpatialAttr,
              threshold_array, weight, distance_matrix, threshold,
              alpha, tabuLength, max_no_move):
    t = 1
    ni_move_ct = 0
    make_move_flag = False
    tabuList = []
    potentialAreas = []

    labels = deepcopy(initLabels)
    regionLists = deepcopy(initRegionList)
    regionSpatialAttrs = deepcopy(initRegionSpatialAttr)

    while ni_move_ct <= max_no_move:
        if len(potentialAreas) == 0:
            potentialAreas = pickMoveArea(labels, regionLists,
                                          regionSpatialAttrs,
                                          threshold_array, weight,
                                          distance_matrix, threshold)

        poa = potentialAreas[np.random.randint(len(potentialAreas))]
        lostDistance, minAddedDistance, potentialMove = checkMove(
            poa, labels, regionLists, threshold_array, weight,
            distance_matrix, threshold)

        if potentialMove == None:
            potentialAreas.remove(poa)
            continue

        diff = lostDistance - minAddedDistance
        donorRegion = potentialMove[1]
        recipientRegion = potentialMove[2]

        if diff > 0:
            make_move_flag = True
            if (poa, recipientRegion, donorRegion) not in tabuList:
                if len(tabuList) == tabuLength:
                    tabuList.pop(0)
                tabuList.append((poa, recipientRegion, donorRegion))

            ni_move_ct = 0
        else:
            ni_move_ct += 1
            prob = np.exp(diff / t)
            if prob > np.random.random() and potentialMove not in tabuList:
                make_move_flag = True
            else:
                make_move_flag = False

        potentialAreas.remove(poa)
        if make_move_flag:
            labels[poa] = recipientRegion
            regionLists[donorRegion].remove(poa)
            regionLists[recipientRegion].append(poa)
            regionSpatialAttrs[donorRegion] -= threshold_array[poa]
            regionSpatialAttrs[recipientRegion] += threshold_array[
                poa]

            impactedAreas = []
            for pa in potentialAreas:
                if labels[pa] == recipientRegion or labels[pa] == donorRegion:
                    impactedAreas.append(pa)
            for pa in impactedAreas:
                potentialAreas.remove(pa)

        t = t * alpha

    return [labels, regionLists, regionSpatialAttrs]





class MaxPHeuristic(BaseSpOptHeuristicSolver):
    def __init__(self, gdf, w, attrs_name, threshold_name, threshold, top_n, max_iterations_construction=99, max_iterations_sa=ITERSA):
        self.gdf = gdf
        self.w = w
        self.attrs_name = attrs_name
        self.threshold_name = threshold_name
        self.threshold = threshold
        self.top_n = top_n
        self.max_iterations_construction = max_iterations_construction
        self.max_iterations_sa = max_iterations_sa

    def solve(self):
        max_p, label = maxp(self.gdf, self.w, self.attrs_name, self.threshold_name,
                            self.threshold, self.top_n, self.max_iterations_construction, self.max_iterations_sa)
        self.labels_ = label
        self.p = max_p

if __name__ == "__main__":
    set_input('data/n100.dbf', ['SAR1'], 'Uniform2', 100, 'result/test.shp', 2,
              999, 10)
