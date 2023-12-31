import io
import json
import base64
import requests
import sys
import wx

from PIL import Image
from ultralytics import YOLO
from flask import Flask, request, jsonify

app = Flask(__name__)

import threading

class ResourcePool:
    def __init__(self, initial_resources):
        self.resources = initial_resources
        self.lock = threading.Lock()

    def get_resource(self):
        with self.lock:
            if not self.resources:
                self.resources.append((YOLO("./best.pt"), YOLO("./best_allocate.pt")))
            return self.resources.pop()

    def return_resource(self, resource):
        with self.lock:
            self.resources.append(resource)

def getRectangularArea(masks_data):
    return masks_data.sum().item()

def isInclusion(wspot_xyxy, rectangular_xyxy):
    x1, y1, x2, y2 = wspot_xyxy
    x3, y3, x4, y4 = rectangular_xyxy
    if (x3<=x1<=x4) and (y3<=y1<=y4):
        return True
    else:
        return False

def getAreaDict(r):
    res = {
        'TOP': {
            'area': 23.5,
            'rectangular_area': None,
            'xyxy': None,
        },
        'MIDDLE': {
            'area': 22.5,
            'rectangular_area': None,
            'xyxy': None,
        },
        'BOTTOM': {
            'area': 28.8,
            'rectangular_area': None,
            'xyxy': None,
        }
    }
    for index, box in enumerate(r.boxes):
        box_key = r.names[box.cls.item()]
        rectangular_xyxy = box.xyxy.numpy().tolist()[0]
        res[box_key]['rectangular_area'] = getRectangularArea(r.masks.data[index])
        res[box_key]['xyxy'] = rectangular_xyxy
    return res

res = []
for _ in range(5):
    res.append((YOLO("./best.pt"), YOLO("./best_allocate.pt")))
rsp = ResourcePool(res)

def getWspotArea(image):
    model_wspot, model_allocate = rsp.get_resource()
    result_wspot = model_wspot(image, imgsz=1280, device='cpu')[0]
    result_allocate = model_allocate(image, imgsz=1280, device='cpu')[0]
    rsp.return_resource((model_wspot, model_allocate))
    
    # 处理三分区
    area_dict = getAreaDict(result_allocate)

    # 计算白斑面积占比
    res_area = []
    res_region = []
    for index, box in enumerate(result_wspot.boxes):
        wspot_xyxy = box.xyxy.cpu().numpy().tolist()[0]
        for key, val in area_dict.items():
            if isInclusion(wspot_xyxy, val['xyxy']):
                wspot_area = round(getRectangularArea(result_wspot.masks.data[index]) / val['rectangular_area'] * val['area'] * 100, 1)
                res_area.append(wspot_area)
                res_region.append(key)
                break
    
    # 合成图像
    image_array = result_wspot.plot(labels=False, boxes=True)
    image = Image.fromarray(image_array[..., ::-1])
    return res_area, res_region, image

# base64 编码图像
def encode_image(image_path):
    return wx.upload_file(image_path)

# 通过 image_id 拿到 image
def decode_image(image_id):
    image_data = wx.get_file_by_id(image_id)
    image = Image.open(image_data)
    return image

@app.route('/process_json', methods=['GET', 'POST'])
def process_json():
    json_post = json.loads(request.get_data())
    image = decode_image(json_post['image_id'])
    
    res_area, res_region, image_yolo = getWspotArea(image)
    image_yolo.save('result.jpg')
    image_id = encode_image('result.jpg')

    # 回传 json 包
    data = {
        'image_id': image_id,
        'area': res_area, # 面积
        'region': res_region, # 区域
    }
    json_response = json.dumps(data)
    return json_response, 200, {"Content-Type":"application/json"}

@app.route('/', methods=['GET'])
def index():
    # 构建测试 json 包
    image_id = encode_image('./test.jpg')
    data = {
        'image_id': image_id
    }
    json_post = json.dumps(data)
    response = requests.post(f'http://{sys.argv[1]}:{sys.argv[2]}/process_json', data=json_post)

    # 拿到回传结果解析图像
    json_result = json.loads(response.text)
    image = decode_image(json_result['image_id'])
    image.save('result1.jpg')
    return 'hello word'
