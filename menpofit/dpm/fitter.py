from menpo.shape import Tree
import numpy as np


def compute_unary_scores(feature_pyramid, filters):
    from menpo.feature.gradient import convolve_python_f  # TODO: define a more proper file for it
    unary_scores = []
    for feat in feature_pyramid:  # for each level in the pyramid
        resp = convolve_python_f(feat, filters)
        unary_scores.append(resp)
    return unary_scores


def compute_pairwise_scores(scores, tree, def_coef, anchor):
    r"""
    Given the (unary) scores it computes the pairwise scores by utilising the Generalised Distance
    Transform.

    Parameters
    ----------
    scores: `list`
        The (unary) scores to which the pairwise score will be added.
    tree: `:map:`Tree``
        Tree with the parent/child connections.
    def_coef: `list`
        Each element contains a 4-tuple with the deformation coefficients for that part.
    anchor:
        Contains the anchor position in relation to the parent of each part.

    Returns
    -------
    scores: `ndarray`
        The (unary + pairwise) scores.
    Ix: `dict`
        Contains the coordinates of x for each part from the Generalised Distance Transform.
    Iy: `dict`
        Contains the coordinates of y for each part from the Generalised Distance Transform.
    """
    from menpo.feature.gradient import call_shiftdt   # TODO: define a more proper file for it.
    Iy, Ix = {}, {}
    for depth in range(tree.maximum_depth, 0, -1):
        for curr_vert in tree.vertices_at_depth(depth):
            (Ny, Nx) = scores[tree.parent(curr_vert)].shape
            w = def_coef[curr_vert]
            cy = anchor[curr_vert][0]
            cx = anchor[curr_vert][1]
            msg, Ix1, Iy1 = call_shiftdt(scores[curr_vert], np.array(w), cx, cy, Nx, Ny, 1)
            scores[tree.parent(curr_vert)] += msg
            Ix[curr_vert] = np.copy(Ix1)
            Iy[curr_vert] = np.copy(Iy1)
    return scores, Ix, Iy


def featpyramid(im, m_inter, sbin, pyra_pad):
    # construct the featpyramid. For the time being, it has similar conventions as in
    # Ramanan's code. TODO: In the future, use menpo's gaussian pyramid.
    from math import log as log_m
    from menpo.feature import hog
    sc = 2 ** (1. / m_inter)
    imsize = (im.shape[0], im.shape[1])
    max_scale = int(log_m(min(imsize)*1./(5*sbin))/log_m(sc)) + 1
    feats, scales = {}, {}
    for i in range(m_inter):
        sc_l = 1. / sc ** i
        scaled = im.rescale(sc_l)
        feats[i] = hog(scaled, mode='sparse', algorithm='zhuramanan', cell_size=sbin/2)
        scales[i] = 2 * sc_l
        feats[i + m_inter] = hog(scaled, mode='sparse', algorithm='zhuramanan', cell_size=sbin)
        scales[i + m_inter] = sc_l

        for j in range(i + m_inter, max_scale, m_inter):
            scaled = scaled.rescale(0.5)
            feats[j + m_inter] = hog(scaled, mode='sparse', algorithm='zhuramanan', cell_size=sbin)
            scales[j + m_inter] = 0.5 * scales[j]

    feats_np = {}  # final feats (keep only numpy array, get rid of the image)
    for k, val in scales.iteritems():
        scales[k] = sbin * 1. / val
        feats_np[k] = np.pad(feats[k].pixels, ((0, 0), (pyra_pad[1] + 1, pyra_pad[1] + 1),
                                               (pyra_pad[0] + 1, pyra_pad[0] + 1)), 'constant')

    return feats_np, scales


def backtrack(x, y, tree, Ix, Iy, fsz, scale, pyra_pad):
    r"""
    Backtrack the solution from the root to the children and return the detection coordinates for each part.

    algorithm:
    (for all points that are greater than the threshold -> vectorised)
    start from the root
    save location of the ln point
    for depth in range(1, max_depth_graph): # traverse tree from the root to the leaves
        curr_ch_vertext = [vertices in current depth]
        for each vertex in curr_ch_vertext:
            find from Ix, Iy the position of the child
            save ideal location of the ln point

    Parameters
    ----------
    x: `list`
        The x coordinates of the detections in the root level.
    y: `list`
        The y coordinates of the detections in the root level.
    tree: `:map:`Tree``
        Tree with the parent/child connections.
    Ix: `dict`
        Contains the coordinates of x for each part from the Generalised Distance Transform.
    Iy: `dict`
        Contains the coordinates of y for each part from the Generalised Distance Transform.
    fsz: `list`
        The size of the filter in the format of [y, x].
        ASSUMPTION: All filters at this level have the same size. Otherwise,
        modify the code for a list of filter sizes.
    scale: `int`
        The scale of the detections in the feature pyramid.
    pyra_pad: `list`
        Padding in the form of [x, y] in the feature pyramid.

    Returns
    -------
    box: `ndarray`
        The x, y coordinates of the detection(s).
    """
    numparts = len(tree.vertices)
    ptr = np.empty((numparts, 2, x.shape[0]), dtype=np.int64)
    box = np.empty((numparts, 4, x.shape[0]))
    k = tree.root_vertex

    ptr[k, 0, :] = np.copy(x)
    ptr[k, 1, :] = np.copy(y)
    box[k, 0, :] = (ptr[k, 0, :] - pyra_pad[0]) * scale + 1
    box[k, 1, :] = (ptr[k, 1, :] - pyra_pad[1]) * scale + 1
    box[k, 2, :] = box[k, 0, :] + fsz[1] * scale - 1
    box[k, 3, :] = box[k, 1, :] + fsz[0] * scale - 1

    for depth in range(1, tree.maximum_depth):
        for cv in tree.vertices_at_depth(depth):  # for each vertex in that level
            par = tree.parent(cv)
            x = ptr[par, 0, :]
            y = ptr[par, 1, :]
            idx = np.ravel_multi_index((y, x), dims=Ix[cv].shape, order='C')
            ptr[cv, 0, :] = Ix[cv].ravel()[idx]
            ptr[cv, 1, :] = Iy[cv].ravel()[idx]

            # exactly the same as bove:
            box[cv, 0, :] = (ptr[cv, 0, :] - pyra_pad[0]) * scale + 1
            box[cv, 1, :] = (ptr[cv, 1, :] - pyra_pad[1]) * scale + 1
            box[cv, 2, :] = box[cv, 0, :] + fsz[1] * scale - 1
            box[cv, 3, :] = box[cv, 1, :] + fsz[0] * scale - 1
    return box


class DPM_fit():
    def __init__(self, tree, filters, def_coef, anchor, bias=0):
        assert(isinstance(tree, Tree))
        assert(len(filters) == len(tree.vertices) == len(def_coef))
        self.tree = tree
        self.filters = filters
        self.def_coef = def_coef
        self.anchor = anchor
        self.bias = bias

    def fit(self, image, threshold=-1):
        from menpo.feature.gradient import convolve_python_f  # TODO: define a more proper file for it.
        padding = (3, 3)  # TODO: param in the future maybe?
        # define filter size in [y, x] format. Assumption: All filters
        # have the same size, otherwise pass a list in backtrack.
        fsz = [self.filters[0].shape[1], self.filters[0].shape[2]]
        feats, scales = featpyramid(image, 5, 4, padding)

        boxes = []  # list with detection boxes (as dictionaries)
        tree = self.tree
        filters = self.filters

        for level, feat in feats.iteritems():  # for each level in the pyramid
            unary_scores = convolve_python_f(feat, filters)

            scores, Ix, Iy = compute_pairwise_scores(np.copy(unary_scores),
                                                     tree, self.def_coef, self.anchor)

            scale = scales[level]
            rscore = scores[tree.root_vertex] + self.bias

            [Y, X] = np.where(rscore > threshold)

            if X.shape[0] > 0:
                XY = backtrack(X, Y, tree, Ix, Iy, fsz, scale, padding)

            for i in range(X.shape[0]):
                x, y = X[i], Y[i]
                detection_info = {}
                detection_info['level'] = level
                detection_info['s'] = np.copy(rscore[y, x])
                detection_info['xy'] = XY[:, :, i]

                boxes.append(dict(detection_info))

        return boxes
