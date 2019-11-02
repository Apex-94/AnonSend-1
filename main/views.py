from collections import Counter

from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404

from .forms import UploadFileForm, PasswordForm, ReportFileForm
from .helper import *
from .models import UploadFile, Analytic

# 2.5MB - 2621440
# 5MB - 5242880
# 10MB - 10485760
# 20MB - 20971520
# 50MB - 5242880
# 100MB - 104857600
# 250MB - 214958080
# 500MB - 429916160
MAX_UPLOAD_SIZE = 104857600


def index(request):
    """
    Displays the front page
    - Includes UploadFileForm
    - Takes input for UploadedFiles model
    - Input includes:
        - File
        - Password (optional, default:blank)
        - Expiry (default:10 Minutes)
        - Max downloads (default: 1)
    :param request: Django request
    :return: index.html
    """
    return render(request, 'index.html', {"form": UploadFileForm()})


def uploaded_link(request):
    """
    - Validates the form from index.html
    - Resolves file collisions by hashing
    - Links are generated with timestamp as seed

    :param request:
    :return: public_link and analytic_link
    """
    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            if len(request.FILES.getlist('file')) > 1:
                # Multiple files, compress to zip
                file = UploadedFile(**compress_to_zip(request.FILES.getlist('file')))
            else:
                # Single file
                file = request.FILES['file']
            if file.size > MAX_UPLOAD_SIZE:
                return render(request, 'size_limit.html')
            # Set defaults for models and also store data retrieved from forms
            model = UploadFile(file=file, file_name=file.name, file_hash=get_hash(file),
                               password=hashPassword(form.cleaned_data['password']),
                               expires_at=form.cleaned_data['expires_at'],
                               max_downloads=form.cleaned_data['max_downloads'])
            # Check for same file with hash
            query_set = UploadFile.objects.all().filter(file_hash=model.file_hash)
            if query_set.exists():
                """ 
                Match found, no need to save
                Only update path
                """
                model.file = query_set.first().file
            else:
                """
                File does not exist,
                store in directory with same hash
                
                *Note*: Separate directory is created to mitigate errors in files with same name different contents
                """
                name = file.name.split("/")
                name.insert(0, model.file_hash)
                name = "/".join(name)
                model.file.save(name, file)
            model.save()
            return render(request, 'upload_success.html',
                          {"public_link": model.public_link, "analytic_link": model.analytic_link})
        else:
            # Form is invalid
            return redirect(index)

    else:
        # Request is not post
        return redirect(index)


def public_link_handle(request, public_link):
    """
    - Serves as download page, intended to be shared via other platforms
    - If password is blank, set to visibility to false i.e hide password field
    - If password is invalid, prompt via messages
    - Finally verify constraints (max_downloads and expiry_at)
    - If within constraints, store info to Analytic model and serve the file

    :type public_link: str
    :param request:
    :param public_link: Uniquely generated public link
    :return: public_link.html
    """
    upload_file = get_object_or_404(UploadFile, pk=public_link)
    download_count = len(Analytic.objects.filter(upload_file=upload_file))
    expires_at = upload_file.expires_at.timestamp()
    current_time = datetime.now().timestamp()
    if download_count <= upload_file.max_downloads and expires_at > current_time:
        if request.method == "POST":
            form = PasswordForm(request.POST, expected_password=upload_file.password)

            if form.is_valid():
                results = get_analytics(request.META)
                Analytic(upload_file_id=public_link, **results).save()
                return FileResponse(upload_file.file, as_attachment=True, filename=upload_file.file_name)
            else:
                return render(request, 'public_link.html',
                              {"form": PasswordForm(expected_password=not verifyPassword('', upload_file.password)),
                               "valid": "is-invalid"})

        else:
            return render(request, 'public_link.html',
                          {"form": PasswordForm(expected_password=not verifyPassword('', upload_file.password)),
                           "valid": ""})

    else:
        raise Http404()


def downloadAsCsv(request, analytic_link):
    query = UploadFile.objects.all().filter(analytic_link=analytic_link)
    if query.exists() and query.first().expires_at.timestamp() > datetime.now().timestamp():
        results = Analytic.objects.filter(upload_file=query.first()).order_by('-time_clicked')
        fname = queryToCsv(results);
        return FileResponse(open(fname, 'rb'), as_attachment=True, filename="Anonsend_analytics.csv")
    else:
        raise Http404()


def analytic_link_handle(request, analytic_link):
    """
    **Beta**
    Display various analytics for the public link such as:
        - OS family (Linux,Windows,Unix,etc)
        - Device type (Mobile,Tablet,Personal Computer)
        - Geolocation (Country,City,State)
        - DateTime public_link was downloaded
    :param request:
    :param analytic_link:
    :return:
    """
    query = UploadFile.objects.all().filter(analytic_link=analytic_link)
    if query.exists() and query.first().expires_at.timestamp() > datetime.now().timestamp():
        results = Analytic.objects.filter(upload_file=query.first()).order_by('-time_clicked')
        device_type = Counter([x for i in list(results.values_list('device_type')) for x in i]).items()
        browser = Counter([x for i in list(results.values_list('browser')) for x in i]).items()
        country = Counter([x for i in list(results.values_list('country')) for x in i]).items()
        return render(request, 'analytics.html',
                      {"country": country, "device_type": device_type, "browser": browser, "results": results,
                       "link": analytic_link})
    else:
        raise Http404()


def report_link(request, public_link):
    if request.method == "POST":
        form = ReportFileForm(request.POST)
        if form.is_valid():
            model = form.save(commit=False)
            model.upload_file = get_object_or_404(UploadFile, pk=public_link)
            model.save()
            return render(request, "report_link.success.html", )
    else:
        # GET request
        form = ReportFileForm()
        return render(request, "report_link.html", {"report_form": form, })


def faq(request):
    return render(request, 'faq.html', {"questions": getQuestions()})
