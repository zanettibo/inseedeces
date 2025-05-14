from django import forms
from .models import DecesImportError

class ImportErrorForm(forms.ModelForm):
    class Meta:
        model = DecesImportError
        fields = ['nom', 'prenoms', 'sexe', 'date_naissance', 'lieu_naissance',
                 'lieu_naissance_nom', 'date_deces', 'lieu_deces', 'acte_deces']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'prenoms': forms.TextInput(attrs={'class': 'form-control'}),
            'sexe': forms.Select(attrs={'class': 'form-control'}),
            'date_naissance': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'date_deces': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'lieu_naissance': forms.TextInput(attrs={'class': 'form-control'}),
            'lieu_naissance_nom': forms.TextInput(attrs={'class': 'form-control'}),
            'lieu_deces': forms.TextInput(attrs={'class': 'form-control'}),
            'acte_deces': forms.TextInput(attrs={'class': 'form-control'}),
        }
