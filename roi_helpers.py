import numpy as np
import math
from config import Config


def apply_regr(x, y, w, h, tx, ty, tw, th):
    try:
        cx = x + w / 2.
        cy = y + h / 2.
        cx1 = tx * w + cx
        cy1 = ty * h + cy
        w1 = math.exp(tw) * w
        h1 = math.exp(th) * h
        x1 = cx1 - w1 / 2.
        y1 = cy1 - h1 / 2.
        x1 = int(round(x1))
        y1 = int(round(y1))
        w1 = int(round(w1))
        h1 = int(round(h1))

        return x1, y1, w1, h1

    except ValueError:
        return x, y, w, h
    except OverflowError:
        return x, y, w, h
    except Exception as e:
        print(e)
        return x, y, w, h


def apply_regr_np(X, T):
    try:
        x = X[0, :, :]
        y = X[1, :, :]
        w = X[2, :, :]
        h = X[3, :, :]

        tx = T[0, :, :]
        ty = T[1, :, :]
        tw = T[2, :, :]
        th = T[3, :, :]

        # tx：是实际框的中心点cx与预选宽的中心点cxa的差值，除以预选框的宽度。ty是同理
        # tw:是实际框的宽度的log除预选宽的宽度，th同理
        cx = x + w / 2.
        cy = y + h / 2.
        cx1 = tx * w + cx
        cy1 = ty * h + cy

        w1 = np.exp(tw.astype(np.float64)) * w
        h1 = np.exp(th.astype(np.float64)) * h
        x1 = cx1 - w1 / 2.
        y1 = cy1 - h1 / 2.

        x1 = np.round(x1)
        y1 = np.round(y1)
        w1 = np.round(w1)
        h1 = np.round(h1)
        return np.stack([x1, y1, w1, h1])
    except Exception as e:
        print(e)
        return X


def non_max_suppression_fast(boxes, num_rectangle, overlap_thresh=0.9, max_boxes=300):
    # I changed this method with boxes already contains probabilities, so don't need prob send in this method
    # TODO: Caution!!! now the boxes actually is [x1, y1, x2, y2, prob] format!!!! with prob built in
    if len(boxes) == 0:
        return []
    # normalize to np.array
    boxes = np.array(boxes)
    # grab the coordinates of the bounding boxes
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    prob_loc = boxes[:, 4]
    np.testing.assert_array_less(x1, x2)
    np.testing.assert_array_less(y1, y2)

    if boxes.dtype.kind == "i":
        boxes = boxes.astype("float")

    pick = []
    area = (x2 - x1) * (y2 - y1)
    # sorted by boxes last element which is prob
    indexes = np.argsort([i[-1] for i in boxes])
    cfg = Config()
    while len(indexes) > 0:
        last = len(indexes) - 1
        i = indexes[last]
        pick.append(i)

        # find the intersection
        xx1_int = np.maximum(x1[i], x1[indexes[:last]])
        yy1_int = np.maximum(y1[i], y1[indexes[:last]])
        xx2_int = np.minimum(x2[i], x2[indexes[:last]])
        yy2_int = np.minimum(y2[i], y2[indexes[:last]])

        ww_int = np.maximum(0, xx2_int - xx1_int)
        hh_int = np.maximum(0, yy2_int - yy1_int)

        area_int = ww_int * hh_int
        # find the union
        area_union = area[i] + area[indexes[:last]] - area_int

        # compute the ratio of overlap
        overlap = area_int / (area_union + 1e-6)

        # delete all indexes from the index list that have
        indexes = np.delete(indexes, np.concatenate(([last], np.where(overlap > overlap_thresh)[0])))

        if len(pick) >= max_boxes:
            break
    # return only the bounding boxes that were picked using the integer data type
    boxes = boxes[pick]
    for i in range(len(pick)):
        class_num = pick[i] // num_rectangle
        if (class_num - 1) < int(cfg.num_anchors):
            boxes[i, 4] = 0
        else:
            boxes[i, 4] = (class_num - 1) // int(cfg.num_anchors)
    return boxes


def rpn_to_roi(rpn_layer, regr_layer, cfg, dim_ordering, use_regr=True, max_boxes=5, overlap_thresh=0.99):
    regr_layer = regr_layer / cfg.std_scaling

    anchor_sizes = cfg.anchor_box_scales
    anchor_ratios = cfg.anchor_box_ratios
    width = rpn_layer.shape[1]
    height = rpn_layer.shape[2]
    num_rectangle = width * height
    assert rpn_layer.shape[0] == 1

    curr_layer = 0

    # rpn_layer.shape (1, width, height, num_anchors * num_regions) 3 * 2 * 4
    # regr_layer.shape (1, width, height, num_anchors * num_regions * 4) 3 * 2 * 4 * 4
    if dim_ordering == 'tf':
        (rows, cols) = rpn_layer.shape[1:3]
        A = np.zeros((4, rpn_layer.shape[1], rpn_layer.shape[2], rpn_layer.shape[3]))

    for anchor_size in anchor_sizes:
        for anchor_ratio in anchor_ratios:
            for num_region in range(cfg.num_regions):
                anchor_x = (anchor_size * anchor_ratio[0]) / cfg.rpn_stride
                anchor_y = (anchor_size * anchor_ratio[1]) / cfg.rpn_stride
                regr = regr_layer[0, :, :, 4 * curr_layer:4 * curr_layer + 4]
                regr = np.transpose(regr, (2, 0, 1))

                # X，Y 都是 cols行，rows列
                X, Y = np.meshgrid(np.arange(cols), np.arange(rows))

                # curr_layer代表的是特定长度和比例的框所代表的编号 1-9
                # 得到anchor对应的（x,y,w,h）
                # 使用regr对anchor所确定的框进行修正
                A[0, :, :, curr_layer] = X - anchor_x / 2
                A[1, :, :, curr_layer] = Y - anchor_y / 2
                A[2, :, :, curr_layer] = anchor_x
                A[3, :, :, curr_layer] = anchor_y

                if use_regr:
                    A[:, :, :, curr_layer] = apply_regr_np(A[:, :, :, curr_layer], regr)

                # 过滤anchor_x 和 anchor_y 使最小也为1
                A[2, :, :, curr_layer] = np.maximum(1, A[2, :, :, curr_layer])
                A[3, :, :, curr_layer] = np.maximum(1, A[3, :, :, curr_layer])
                A[2, :, :, curr_layer] += A[0, :, :, curr_layer]
                A[3, :, :, curr_layer] += A[1, :, :, curr_layer]

                A[0, :, :, curr_layer] = np.maximum(0, A[0, :, :, curr_layer])
                A[1, :, :, curr_layer] = np.maximum(0, A[1, :, :, curr_layer])
                A[2, :, :, curr_layer] = np.minimum(cols - 1, A[2, :, :, curr_layer])
                A[3, :, :, curr_layer] = np.minimum(rows - 1, A[3, :, :, curr_layer])

                curr_layer += 1
                # 这段代码主要是对修正后的边框一些不合理的地方进行矫正。
                # 如，边框回归后的左上角和右下角的点不能超过图片外，框的宽高不可以小于0
                # 注：得到框的形式是（x1,y1,x2,y2）
    all_boxes = np.reshape(A.transpose((0, 3, 1, 2)), (4, -1)).transpose((1, 0))
    all_probs = rpn_layer.transpose((0, 3, 1, 2)).reshape((-1))
    print('-------all_probs------')
    print(all_probs)
    print('-------all_probs------')
    # 得到all_boxes形状是（n,4），和每一个框对应的概率all_probs形状是（n,）
    x1 = all_boxes[:, 0]
    y1 = all_boxes[:, 1]
    x2 = all_boxes[:, 2]
    y2 = all_boxes[:, 3]

    ids = np.where((x1 - x2 >= 0) | (y1 - y2 >= 0))

    all_boxes = np.delete(all_boxes, ids, 0)
    all_probs = np.delete(all_probs, ids, 0)

    # 删除掉一些不合理的点，即右下角的点值要小于左上角的点值
    # 注：np.where() 返回位置信息，这也是删除不符合要求点的一种方法
    #   np.delete(all_boxes, idxs, 0)最后一个参数是在哪一个维度删除
    # I guess boxes and prob are all 2d array, I will concat them
    all_boxes = np.hstack((all_boxes, np.array([[p] for p in all_probs])))
    result = non_max_suppression_fast(all_boxes, num_rectangle, overlap_thresh=overlap_thresh, max_boxes=max_boxes)
    # omit the last column which is prob
    # result = result[:, 0: -1]
    return result


if __name__ == '__main__':
    test_x, test_y = np.meshgrid(np.arange(5), np.arange(4))
    A = np.zeros((2, 3))
    A[1, :] = 5
    # print(A)
    B = np.zeros((2, 3))
    B[1, 1] = 2
    print(B[1:])
    # print(test_x)
    # print(test_y)