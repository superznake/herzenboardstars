from django import forms
from .models import SuggestedCategory, SuggestedNominee

# =========================
# Форма для предложения категории
# =========================

class SuggestedCategoryForm(forms.ModelForm):
    class Meta:
        model = SuggestedCategory
        fields = ['name', 'description']
        labels = {
            'name': 'Название номинации',
            'description': 'Описание',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите название номинации'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Описание (необязательно)',
                'rows': 3
            }),
        }


# =========================
# Форма для предложения номинанта
# =========================
class SuggestedNomineeForm(forms.ModelForm):
    class Meta:
        model = SuggestedNominee
        fields = ['name', 'description']
        labels = {
            'name': 'Имя номинанта',
            'description': 'Описание',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Введите имя номинанта'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Описание (необязательно)',
                'rows': 3
            }),
        }
