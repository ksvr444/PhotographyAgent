import pyrebase
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
from django.shortcuts import redirect
import os
import uuid
import base64
from io import BytesIO
from datetime import datetime
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
import pyrebase
import replicate
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
from openai import OpenAI
from PIL import Image
from django.views.decorators.cache import cache_control
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import shutil



firebase = pyrebase.initialize_app(settings.FIREBASE_CONFIG)
auth = firebase.auth()

def login(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            request.session['uid'] = user['idToken']
            request.session['email'] = email
            return redirect('train')

        except:
            print('Invalid credentials')
    return render(request, 'login.html')


def logout(request):
    # Clear the session data
    request.session.flush()
    # Redirect to the login page
    return redirect('login')

def home(request):
    if not request.session.get('uid'):
        return redirect('login')
    return render(request, 'home.html')



storage = firebase.storage()
db = firebase.database()

# Initialize OpenAI
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

# Initialize Replicate
replicate_client = replicate.Client(api_token=settings.REPLICATE_API_TOKEN)

@cache_control(no_cache=True, must_revalidate=True, no_store=True)
def train_model(request):
    os.system('cls' if os.name == 'nt' else 'clear')

    if not request.session.get('uid'):
        return redirect('login')
    
    if request.method == 'POST':
        # Get form data
        model_name = request.POST.get('model_name')
        
        training_images = request.FILES.getlist('training_images_p1') + request.FILES.getlist('training_images_p2') + request.FILES.getlist('training_images_co')
    
        user_email = request.session.get('email')  # Assuming user email is stored in session
        user_email_glob = user_email
        # Generate a unique model ID
        model_id = str(uuid.uuid4())

        # Upload images to Firebase and generate descriptions
        image_urls = []
        image_descriptions = []


        # Create a directory to store images and descriptions
        zip_dir = f"./zippedImages/{model_id}"
        os.makedirs(zip_dir, exist_ok=True)


        # Save images and descriptions to the directory
        for idx, image in enumerate(training_images):
            image_path = os.path.join(zip_dir, f"image_{idx}.jpeg")
            with open(image_path, 'wb') as img_file:
                img_file.write(image.read())

            # Save image to Firebase Storage
            firebase_image_path = f"PhotographyImages/{user_email}/{model_name}/image_{idx}.jpeg"
            storage.child(firebase_image_path).put(image)
            image_url = storage.child(firebase_image_path).get_url(None)
            image_urls.append(image_url)

            # Generate image description using OpenAI
            image = Image.open(image)
            if idx < 5:
                prompt = "Describe the person in image in 3 sentences, focusing on the person's face, appearance, actions, and surroundings, using the person name as aabbcc"
                # continue
            elif idx < 10:
                prompt = "Describe the person in image in 3 sentences, focusing on the person's face, appearance, actions, and surroundings, using the person name as ccbbaa"
                # continue
            else:
                prompt = "Describe the persons in image in 3 sentences, focusing on the persons faces, appearance, actions, and surroundings, using person name as aabbcc who is on left and person name as ccbbaa who is to the right"

            description = generate_description(image, prompt)

            # description = f"This is a description {idx}"
            image_descriptions.append(description)
            description_path = os.path.join(zip_dir, f"description_{idx}.txt")
            with open(description_path, 'w') as desc_file:
                desc_file.write(description)

        # Zip the directory
        shutil.make_archive(zip_dir, 'zip', zip_dir)


        # # Check if the model already exists
        # existing_models = db.child("models").order_by_child("modelName").equal_to(model_name).get().val()
        # print(existing_models)
        # if existing_models:
        #     messages.add_message(request, messages.ERROR, 'Model with this name already exists.')
        #     return redirect('train')

        # Initiate training with Replicate
        
        # Create a new model on Replicate
        model = replicate_client.models.create(
            owner='ksvr444',
            name=model_name,
            visibility="private",
            hardware="gpu-t4",
            description=f"A fine-tuned FLUX.1 model for {user_email}",
        )

        # Start training
        training = replicate_client.trainings.create(
            version="ostris/flux-dev-lora-trainer:b6af14222e6bd9be257cbc1ea4afda3cd0503e1133083b9d1de0364d8568e6ef",
            input={
                "input_images": open(zip_dir + ".zip", 'rb'),
                "steps": 1000,
                "lora_rank": 16,
                "optimizer": "adamw8bit",
                "batch_size": 1,
                "resolution": "512,768,1024",
                "autocaption": False,
                "trigger_word": "TOKQQ",
                "learning_rate": 0.0004,
                "caption_dropout_rate": 0.05,
                "cache_latents_to_disk": False,
                "gradient_checkpointing": False,
                "hf_token": settings.HUGGINGFACE_TOKEN,
                "hf_repo_id": f"ksvr444masters/{model.owner}/{model.name}",
                "model_id" : model_id,
                "email": user_email,
                "image_descriptions": image_descriptions,
                "image_urls": image_urls,
            },
            webhook='https://photographyproject-2715650954.us-west1.run.app/replicate-webhook/', 
            # webhook_events_filter=["completed"],
            destination=f"{model.owner}/{model.name}",
        )

        messages.add_message(request, messages.SUCCESS, 'Model training started successfully.')



    # Fetch user-specific models from Firebase
    user_email = request.session.get('email')  # Assuming user email is stored in session
    user_models = db.child("models").order_by_child("input/email").equal_to(str(user_email)).get().val()


    # Convert Firebase data to a list of models
    models_list = []
    if user_models:
        for id, model_data in user_models.items():
           
            models_list.append({
                "modelId": id,
                "modelName": model_data.get('output')['version'].split(":")[0],
            })

    return render(request, 'train.html', {"user_models": models_list, 'user_email': user_email})





@csrf_exempt  # Disable CSRF protection for this view (required for external POST requests)
def replicate_webhook(request):
    if request.method == 'POST':
        try:
            # Parse the incoming JSON data
            data = json.loads(request.body)
            
            # Extract relevant information from the webhook payload
            training_id = data.get('id')  # Unique ID of the training job
            status = data.get('status')   # Status of the training job (e.g., "completed", "failed")
            complete_model_name = data.get('output')['version']  # Name of the model being trained
            user_email = data.get('input')['email'] # Email of the user who initiated the training
            model_id = data.get('input')['model_id'] # Model ID in Firebase

            db.child("models").child(model_id).set(data)

            print(f"Received webhook for training ID: {training_id}, Status: {status} to {user_email}")
            send_email_notification(user_email, status, complete_model_name)
            
            
            # Return a success response
            return JsonResponse({'status': 'success'})
        
        except Exception as e:
            # Log the error
            print(f"Error processing webhook: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    # Return an error response for non-POST requests
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)



# Function to generate image descriptions using a vision model
def generate_description(image, prompt):
    # Convert image to bytes
    buffered = BytesIO()
    image.save(buffered, format="JPEG")
    base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                        },
                    },
                ],
            }
        ],
        max_tokens=300,
    )

    return response.choices[0].message.content




def send_email_notification(user_email, status, model_name):
    sg = SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
    from_email = Email("ksvr444masters@gmail.com")  # Change to your verified sender
    to_email = To(user_email)  # Change to your recipient
    subject = "Training Completed"
    content = Content("text/plain", f"Model name: {model_name}\nstatus: {status}")
    mail = Mail(from_email, to_email, subject, content)

    # Send email
    response = sg.client.mail.send.post(request_body=mail.get())
    print(response.status_code)
    print(response.headers)






@csrf_exempt
def generate_image(request):
    os.system('cls' if os.name == 'nt' else 'clear')
    if request.method == 'POST':
        try:
            # Parse request data
            data = json.loads(request.body)
            model_id = data.get("modelId")
            prompt = "TOKQQ" + data.get("prompt")

            # Fetch model details from Firebase
            model_data = db.child("models").child(model_id).get().val()
            model_name = model_data.get('output')['version']
            
            if not model_data:
                return JsonResponse({"error": "Model not found"}, status=404)
            



            print(model_name)
            # Generate image using Replicate
            output = replicate_client.run(
                model_name,
                input={
                    "prompt": prompt,
                    "num_inference_steps": 28,
                    "guidance_scale": 7.5,
                    "model": "dev",
                }
            )
            # Get the image data from the output
            image_data = output[0].read()
            print(output[0])

            # Convert image data to base64
            image_base64 = base64.b64encode(image_data).decode('utf-8')

            # Return the base64-encoded image
            return JsonResponse({"image_url": f"data:image/png;base64,{image_base64}"})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=400)