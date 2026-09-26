import numpy as np
import cv2

def postprocess_yolov8(outputs, original_shape, scale, dw, dh, conf_thres, nms_thres,
                       keep_class_ids=None):
    """YOLOv8 后处理（2026-09-26 向量化重写，CHARTER v1.3 硬约束）。

    旧实现逐框 Python 循环 8400 个预测、每框 ``np.argmax(80 元素)`` ——
    实测占整帧 **43%**（33 ms/帧，`probe_detector_stage_cost.py`，
    两遍换顺序复测一致）。本版全程 numpy 向量化，同一输入的输出与旧实现
    **逐字节一致**（`verify_postprocess_vec.py` 用 git HEAD 旧版对拍）。

    ``keep_class_ids``：可选的类别白名单（CHARTER v1.3「目标类别只有
    行人」—— 传 person 的 class_id 集合）。语义是 **argmax 判定**：
    预测框的 argmax 类别不在白名单里就整个丢弃（在进 NMS **之前**，
    少喂 NMS 也是提速的一部分）—— **不会**把「argmax=car 0.86 而
    person=0.42」的框重标成 person 0.42（那等于把车框伪造成行人）。
    ``None`` = 不过滤。

    与旧实现刻意保持一致的细节（对拍的要求，别"顺手优化"掉）：
    - 坐标做 ``int()`` 截断（向零取整）后才用于 NMS 框计算；
    - NMS 输入格式 ``(left, top, w, h)``、score_threshold 传 ``conf_thres``
      （与旧调用完全相同）；
    - 结果顺序 = 预测行序（升序）经 NMS 索引重排。
    """
    orig_w, orig_h = original_shape
    if isinstance(outputs, (list, tuple)):
        # 每个输出 shape (1, 84, N)，取第一个 batch 后按预测维拼接
        pred = np.concatenate([out[0] for out in outputs], axis=1)
    else:
        pred = outputs[0] if outputs.ndim == 3 else outputs
    pred = pred.transpose(1, 0)                     # (8400, 84)

    boxes = pred[:, :4]                             # 画布坐标 cx, cy, w, h
    scores = pred[:, 4:]                            # (8400, num_classes)
    class_ids = np.argmax(scores, axis=1)
    conf = scores[np.arange(scores.shape[0]), class_ids]

    mask = conf >= conf_thres
    if keep_class_ids is not None and len(keep_class_ids) > 0:
        mask &= np.isin(class_ids, np.asarray(sorted(keep_class_ids),
                                              dtype=np.int64))
    sel = np.nonzero(mask)[0]
    if sel.size == 0:
        return []

    # 画布坐标 → 原图坐标（letterbox 反变换），全部向量化
    cx = np.clip((boxes[sel, 0] - dw) / scale, 0, orig_w)
    cy = np.clip((boxes[sel, 1] - dh) / scale, 0, orig_h)
    w = np.minimum(boxes[sel, 2] / scale, orig_w)
    h = np.minimum(boxes[sel, 3] / scale, orig_h)
    # int() 截断（向零取整，与旧实现一致——坐标已 clip 到 >= 0，等价于取整）
    cx = cx.astype(np.int64)
    cy = cy.astype(np.int64)
    w = w.astype(np.int64)
    h = h.astype(np.int64)
    conf_s = conf[sel]
    cid_s = class_ids[sel]

    detections = [
        {'x': int(cx[i]), 'y': int(cy[i]), 'width': int(w[i]),
         'height': int(h[i]), 'confidence': float(conf_s[i]),
         'class_id': int(cid_s[i])}
        for i in range(sel.size)
    ]

    # NMS（与旧实现相同的调用：4 元组 (left, top, w, h)、conf_thres 复用作
    # score_threshold）。旧版此处有一个**每帧打印** NMS 索引的调试输出，
    # 已删 —— 它在生产路径上每帧刷一行日志。
    nms_boxes = [[int(cx[i]) - int(w[i]) / 2, int(cy[i]) - int(h[i]) / 2,
                  int(w[i]), int(h[i])] for i in range(sel.size)]
    indices = cv2.dnn.NMSBoxes(nms_boxes, conf_s.tolist(),
                               float(conf_thres), float(nms_thres))
    if len(indices) > 0:
        indices = indices.flatten()
        return [detections[i] for i in indices]
    return []


def postprocess_yolov5(outputs, original_shape, scale, dw, dh, conf_thres, nms_thres):
    """YOLOv5 后处理，返回检测框列表"""
    detections = []
    orig_w, orig_h = original_shape
    # outputs 是列表，通常第一个元素是 (1,25200,85)
    pred = outputs[0][0]  # shape (25200, 85)
    for det in pred:
        # det: [x_center, y_center, width, height, objectness, class_scores...]
        x_center, y_center, box_w, box_h, obj_conf = det[:5]
        class_scores = det[5:]
        class_id = np.argmax(class_scores)
        conf = obj_conf * class_scores[class_id]
        if conf < conf_thres:
            continue
        # 坐标是归一化的（0~1），需要乘以 640 得到画布坐标
        cx_canvas = x_center 
        cy_canvas = y_center 
        w_canvas = box_w 
        h_canvas = box_h 
        # 映射回原始图像
        cx_orig = (cx_canvas - dw) / scale
        cy_orig = (cy_canvas - dh) / scale
        w_orig = w_canvas / scale
        h_orig = h_canvas / scale
        cx_orig = np.clip(cx_orig, 0, orig_w)
        cy_orig = np.clip(cy_orig, 0, orig_h)
        w_orig = min(w_orig, orig_w)
        h_orig = min(h_orig, orig_h)
        detections.append({
            'x': int(cx_orig),
            'y': int(cy_orig),
            'width': int(w_orig),
            'height': int(h_orig),
            'confidence': float(conf),
            'class_id': int(class_id)
        })
    # NMS 与 v8 相同
    if detections:
        boxes = np.array([[d['x'] - d['width']/2, d['y'] - d['height']/2, d['width'], d['height']] for d in detections])
        confs = np.array([d['confidence'] for d in detections])
        indices = cv2.dnn.NMSBoxes(boxes.tolist(), confs.tolist(), conf_thres, nms_thres)
        if len(indices) > 0:
            indices = indices.flatten()
            detections = [detections[i] for i in indices]
        else:
            detections = []
    return detections
    
def postprocess_yolov8_ncnn(outputs, original_shape, scale, dw, dh, conf_thres, nms_thres):
    """
    专门为NCNN转换的YOLOv8模型设计的后处理函数，带详细调试信息
    outputs: 列表，包含一个形状为 (1,84,8400) 的数组
    """
    detections = []
    orig_w, orig_h = original_shape

    # 获取预测张量 (84, 8400)
    pred = outputs[0][0]  # (84, 8400)
    print("\n========== 后处理调试开始 ==========")
    print(f"原始图像尺寸: ({orig_w}, {orig_h})")
    print(f"预处理参数: scale={scale:.3f}, dw={dw}, dh={dh}")

    # 定义三个尺度的参数
    strides = [8, 16, 32]
    grid_sizes = [80, 40, 20]
    # 计算每个尺度的起始索引 (基于你之前验证的划分)
    idx_start = [0, 80*80, 80*80 + 40*40]  # [0, 6400, 8000]
    idx_end = [80*80, 80*80 + 40*40, 8400] # [6400, 8000, 8400]

    for si, (stride, grid_size, start, end) in enumerate(zip(strides, grid_sizes, idx_start, idx_end)):
        print(f"\n--- 尺度 {si}: stride={stride}, grid={grid_size}x{grid_size}, 索引范围 {start}-{end-1} ---")

        # 提取当前尺度的预测数据 (84, N)
        scale_pred = pred[:, start:end]
        num_boxes = scale_pred.shape[1]
        print(f"  当前尺度预测框数: {num_boxes}")

        # 分离回归参数 (前64行) 和类别分数 (后80行)
        reg = scale_pred[:64, :]   # (64, N)
        cls = scale_pred[64:, :]   # (80, N)

        # 打印一些统计信息
        print(f"  回归参数统计: min={reg.min():.3f}, max={reg.max():.3f}, mean={reg.mean():.3f}")
        print(f"  类别分数统计: min={cls.min():.3f}, max={cls.max():.3f}, mean={cls.mean():.3f}")

        # 生成网格坐标 (col, row)
        # 每个预测框对应一个网格点，索引 i 对应网格 (i % grid_size, i // grid_size)
        col = np.arange(num_boxes) % grid_size
        row = np.arange(num_boxes) // grid_size

        # ----- 解码回归参数 -----
        # 将 reg 从 (64, N) 转为 (4, 16, N) 并做 softmax (DFL解码)
        reg_reshaped = reg.reshape(4, 16, -1)  # (4,16,N)
        # 对每个16维向量做 softmax
        reg_softmax = np.exp(reg_reshaped - np.max(reg_reshaped, axis=1, keepdims=True))
        reg_softmax = reg_softmax / np.sum(reg_softmax, axis=1, keepdims=True)  # (4,16,N)

        # 计算期望偏移 (每个回归值在0~15之间)
        proj = np.arange(16).reshape(1, 16, 1)  # (1,16,1)
        offset = np.sum(reg_softmax * proj, axis=1)  # (4,N)
        # offset 是相对于网格的偏移量，单位是特征图像素 (0~15)

        print(f"  解码后的偏移量 offset 统计: min={offset.min():.3f}, max={offset.max():.3f}, mean={offset.mean():.3f}")

        # 计算网格的绝对坐标 (特征图尺度)
        grid_x = col.astype(np.float32)
        grid_y = row.astype(np.float32)

        # 计算中心点坐标 (特征图尺度)
        x_center_feat = grid_x + offset[0, :]  # 加上 x 偏移
        y_center_feat = grid_y + offset[1, :]  # 加上 y 偏移
        width_feat = offset[2, :]               # 宽度偏移
        height_feat = offset[3, :]               # 高度偏移

        print(f"  特征图尺度: x_center范围 [{x_center_feat.min():.2f}, {x_center_feat.max():.2f}]")
        print(f"               y_center范围 [{y_center_feat.min():.2f}, {y_center_feat.max():.2f}]")
        print(f"               width范围 [{width_feat.min():.2f}, {width_feat.max():.2f}]")
        print(f"               height范围 [{height_feat.min():.2f}, {height_feat.max():.2f}]")

        # 转换为输入图像 (640x640) 上的画布坐标
        x_center_canvas = x_center_feat * stride
        y_center_canvas = y_center_feat * stride
        width_canvas = width_feat * stride
        height_canvas = height_feat * stride

        print(f"  画布坐标 (640x640): x_center范围 [{x_center_canvas.min():.2f}, {x_center_canvas.max():.2f}]")
        print(f"                    y_center范围 [{y_center_canvas.min():.2f}, {y_center_canvas.max():.2f}]")
        print(f"                    width范围 [{width_canvas.min():.2f}, {width_canvas.max():.2f}]")
        print(f"                    height范围 [{height_canvas.min():.2f}, {height_canvas.max():.2f}]")

        # ----- 解码类别分数 -----
        # 对类别分数做 sigmoid (如果模型输出已经是概率，可以跳过)
        cls_scores = cls  # 形状 (80, N)
        # 计算每个框的最大概率和类别
        conf = np.max(cls_scores, axis=0)
        class_ids = np.argmax(cls_scores, axis=0)

        print(f"  置信度统计: min={conf.min():.3f}, max={conf.max():.3f}, mean={conf.mean():.3f}")

        # 筛选置信度高于阈值的框
        mask = conf >= conf_thres
        num_passed = np.sum(mask)
        print(f"  置信度阈值 {conf_thres} 后剩余框数: {num_passed}")

        if num_passed == 0:
            continue

        # 只保留满足条件的框
        x_center_canvas = x_center_canvas[mask]
        y_center_canvas = y_center_canvas[mask]
        width_canvas = width_canvas[mask]
        height_canvas = height_canvas[mask]
        conf = conf[mask]
        class_ids = class_ids[mask]

        # 映射回原始图像坐标 (考虑填充)
        cx_orig = (x_center_canvas - dw) / scale
        cy_orig = (y_center_canvas - dh) / scale
        w_orig = width_canvas / scale
        h_orig = height_canvas / scale

        # 边界裁剪
        cx_orig = np.clip(cx_orig, 0, orig_w)
        cy_orig = np.clip(cy_orig, 0, orig_h)
        w_orig = np.minimum(w_orig, orig_w)
        h_orig = np.minimum(h_orig, orig_h)

        print(f"  映射回原图后的坐标: x范围 [{cx_orig.min():.2f}, {cx_orig.max():.2f}]")
        print(f"                      y范围 [{cy_orig.min():.2f}, {cy_orig.max():.2f}]")

        # 添加到检测列表
        for i in range(len(conf)):
            detections.append({
                'x': int(cx_orig[i]),
                'y': int(cy_orig[i]),
                'width': int(w_orig[i]),
                'height': int(h_orig[i]),
                'confidence': float(conf[i]),
                'class_id': int(class_ids[i])
            })

    # NMS
    if detections:
        print(f"\nNMS 前检测框数量: {len(detections)}")
        # 转换为 (x1,y1,x2,y2) 格式
        boxes = np.array([[d['x'] - d['width']/2,
                           d['y'] - d['height']/2,
                           d['x'] + d['width']/2,
                           d['y'] + d['height']/2] for d in detections])
        confs = np.array([d['confidence'] for d in detections])
        indices = cv2.dnn.NMSBoxes(boxes.tolist(), confs.tolist(), conf_thres, nms_thres)
        if len(indices) > 0:
            indices = indices.flatten()
            detections = [detections[i] for i in indices]
        print(f"NMS 后检测框数量: {len(detections)}")
    print("========== 后处理调试结束 ==========\n")
    return detections

def postprocess_yolov5_ncnn(outputs, original_shape, scale, dw, dh, conf_thres, nms_thres):
    """
    针对YOLOv5 NCNN输出（logits）的向量化后处理，速度更快
    outputs: 列表，包含一个形状为 (1,25200,85) 的数组
    """
    detections = []
    orig_w, orig_h = original_shape

    # 获取预测张量 (25200, 85)
    pred = outputs[0][0]  # (25200, 85)

    # 提取所有框的数据
    x_center = pred[:, 0]
    y_center = pred[:, 1]
    width = pred[:, 2]
    height = pred[:, 3]
    obj_conf = pred[:, 4]
    class_scores = pred[:, 5:]  # (25200, 80)

    # 应用 sigmoid
    obj_conf = 1 / (1 + np.exp(-obj_conf))
    class_scores = 1 / (1 + np.exp(-class_scores))

    # 计算每个框的置信度和类别
    conf = np.max(class_scores, axis=1) * obj_conf
    class_ids = np.argmax(class_scores, axis=1)

    # 筛选置信度高于阈值的框
    mask = conf >= conf_thres
    if not np.any(mask):
        return []

    x_center = x_center[mask]
    y_center = y_center[mask]
    width = width[mask]
    height = height[mask]
    conf = conf[mask]
    class_ids = class_ids[mask]

    # 坐标反归一化（乘以640）
    cx_canvas = x_center * 640
    cy_canvas = y_center * 640
    w_canvas = width * 640
    h_canvas = height * 640

    # 映射回原始图像（考虑填充）
    cx_orig = (cx_canvas - dw) / scale
    cy_orig = (cy_canvas - dh) / scale
    w_orig = w_canvas / scale
    h_orig = h_canvas / scale

    cx_orig = np.clip(cx_orig, 0, orig_w)
    cy_orig = np.clip(cy_orig, 0, orig_h)
    w_orig = np.minimum(w_orig, orig_w)
    h_orig = np.minimum(h_orig, orig_h)

    # 组装结果
    for i in range(len(conf)):
        detections.append({
            'x': int(cx_orig[i]),
            'y': int(cy_orig[i]),
            'width': int(w_orig[i]),
            'height': int(h_orig[i]),
            'confidence': float(conf[i]),
            'class_id': int(class_ids[i])
        })

    # NMS
    if detections:
        boxes = np.array([[d['x'] - d['width']/2, d['y'] - d['height']/2,
                           d['x'] + d['width']/2, d['y'] + d['height']/2] for d in detections])
        confs = np.array([d['confidence'] for d in detections])
        indices = cv2.dnn.NMSBoxes(boxes.tolist(), confs.tolist(), conf_thres, nms_thres)
        if len(indices) > 0:
            indices = indices.flatten()
            detections = [detections[i] for i in indices]
    return detections