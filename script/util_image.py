import cv2
import numpy as np
from mss import mss

sct = mss()

def grab_region(rect, pad=5):
    monitor = {
        "left": max(rect["x"] - pad, 0),
        "top": max(rect["y"] - pad, 0),
        "width": rect["width"] + pad * 2,
        "height": rect["height"] + pad * 2
    }
    img = np.array(sct.grab(monitor))
    return img[:, :, :3]  # 去掉 alpha channel


def detect_template(region_img, template_img, threshold=0.85):
    res = cv2.matchTemplate(region_img, template_img, cv2.TM_CCOEFF_NORMED)
    loc = np.where(res >= threshold)
    if len(loc[0]) > 0:
        # 取出第一個符合 threshold 的位置
        y = loc[0][0]
        x = loc[1][0]
        score = res[y, x]

        # print(f"loc ({threshold} up) = ({x}, {y}), score = {score:.4f}")
        return True
    else:
        return False
