from flask import Flask, render_template, request, jsonify
import boto3
from botocore.exceptions import ClientError
import base64
from PIL import Image
import io
from werkzeug.utils import secure_filename
import os
from dotenv import load_dotenv

app = Flask(__name__)

# Your AWS credentials and region

load_dotenv()
aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
region = os.getenv("AWS_REGION")

brt = boto3.client(service_name="bedrock-runtime", 
                   aws_access_key_id=aws_access_key_id, 
                   aws_secret_access_key=aws_secret_access_key, 
                   region_name=region)

br = boto3.client(service_name="bedrock", 
                   aws_access_key_id=aws_access_key_id, 
                   aws_secret_access_key=aws_secret_access_key, 
                   region_name=region)

model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# Store conversation history
conversation_history = []


def get_image_format(image_bytes):
    """Detect image format from bytes"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        fmt = img.format.lower()
        # Convert JPEG to jpeg for consistency
        if fmt == 'jpeg':
            return 'jpeg'
        elif fmt in ['png', 'gif', 'webp']:
            return fmt
        else:
            return None
    except Exception as e:
        raise Exception(f"Error detecting image format: {e}")


@app.route('/')
def home():
    global conversation_history
    conversation_history = []  # Clear history when page loads
    return render_template('index.html')

@app.route('/clear_history', methods=['POST'])
def clear_history():
    global conversation_history
    conversation_history = []
    return jsonify({"status": "success"})

@app.route('/get_models', methods=['GET'])
def get_models():
    try:
        models = br.list_foundation_models()
        model_list = []
        for m in models['modelSummaries']:
            if m['inferenceTypesSupported']==['ON_DEMAND'] and m['modelLifecycle']['status']=='ACTIVE':
                model_list.append({
                    'modelId': m['modelId'],
                    'modelName': m['modelName'],
                    'modalities': m['inputModalities']
                })
            elif m['inferenceTypesSupported']==['INFERENCE_PROFILE'] and m['modelLifecycle']['status']=='ACTIVE':
                if region.split('-')[0]=="eu" or region.split('-')[0]=="us":
                    model_list.append({
                        'modelId': region.split('-')[0]+"."+m['modelId'],
                        'modelName': m['modelName'],
                        'modalities': m['inputModalities']
                    })
        return jsonify({"models": model_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/upload_image', methods=['POST'])
def upload_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file:
        try:
            # Read the image file
            image_bytes = file.read()
            # Encode to base64 for preview (optional)
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')
            _ = get_image_format(image_bytes)
            filename = secure_filename(file.filename)
            
            return jsonify({
                'filename': filename,
                'preview': image_b64
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/upload_document', methods=['POST'])
def upload_document():
    if 'document' not in request.files:
        return jsonify({'error': 'No document file provided'}), 400
    
    file = request.files['document']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file:
        try:
            # Read the document file
            document_bytes = file.read()
            # Encode to base64
            document_b64 = base64.b64encode(document_bytes).decode('utf-8')
            filename = secure_filename(file.filename)
            if filename.split('.')[-1].lower() not in ['pdf', 'csv', 'doc', 'docx', 'xls', 'xlsx', 'html', 'txt', 'md']:
                raise Exception("Invalid document format. Supported formats: 'pdf', 'csv', 'doc', 'docx', 'xls', 'xlsx', 'html', 'txt', 'md'")
            
            return jsonify({
                'filename': filename,
                'preview': document_b64
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/send_message', methods=['POST'])
def send_message():
    print("Received request")
    
    if not request.is_json:
        print("Request is not JSON")
        return jsonify({"error": "Request must be JSON"}), 400
    
    try:
        data = request.get_json()
        user_message = data['message']
        params = data['params']
        model_id = data.get('modelId', "anthropic.claude-3-5-sonnet-20241022-v2:0")
        system_prompt = data.get('systemPrompt', '').strip()
        image_data = data.get('image')
        document_data = data.get('document')
        # print("Model ID:", model_id)
        
        content = [{"text": user_message}]
        
        if image_data:
            # Decode base64 image
            image_bytes = base64.b64decode(image_data)
            image_format = get_image_format(image_bytes)
            content.append({
                "image": {
                    "format": image_format,
                    "source": {
                        "bytes": image_bytes
                    }
                }
            })

        if document_data:
            # Decode base64 document
            document_bytes = base64.b64decode(document_data)
            document_filename = data.get('documentFilename', '').split('.')[0]
            document_format = data.get('documentFilename', '').split('.')[-1].lower()
            
            content.append({
                "document": {
                    "format": document_format,
                    "name": document_filename,
                    "source": {
                        "bytes": document_bytes
                    }
                }
            })
        
        conversation_history.append({
            "role": "user",
            "content": content
        })
        
        try:
            if system_prompt:
                response = brt.converse(
                    modelId=model_id,
                    messages=conversation_history,
                    inferenceConfig={
                        "maxTokens": int(params['maxTokens']),
                        "temperature": float(params['temperature']),
                        "topP": float(params['topP'])
                    },
                    system=[{"text": system_prompt}]
                )
            else:
                response = brt.converse(
                    modelId=model_id,
                    messages=conversation_history,
                    inferenceConfig={
                        "maxTokens": int(params['maxTokens']),
                        "temperature": float(params['temperature']),
                        "topP": float(params['topP'])
                    },
                )
            
            response_text = response["output"]["message"]["content"][0]["text"]
            
            # Add assistant response to conversation history
            conversation_history.append({
                "role": "assistant",
                "content": [{"text": response_text}],
            })
            
            return jsonify({"response": response_text})
            
        except (ClientError, Exception) as e:
            return jsonify({"error": str(e)}), 500
            
    except Exception as e:
        print("Server error:", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    url = f"http://localhost:5000/"
    os.system(f"start {url}")
    app.run(debug=False, host="127.0.0.1", port=5000)
