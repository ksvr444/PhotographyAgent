from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login, name='login'),
    path('home/', views.home, name='home'),
    path('logout/', views.logout, name='logout'),  # Add this line
    path('train/', views.train_model, name='train'),
    path('generate/', views.generate_image, name='generate'),  # Add this line
    path('replicate-webhook/', views.replicate_webhook, name='replicate_webhook'),
    

]