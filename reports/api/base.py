from rest_framework import renderers, status, views
from rest_framework.response import Response
from rest_framework.settings import api_settings


class BaseReport(views.APIView):
    """
    Base view for reports.

    To create a new report override this class and implement:
        - Serializer that validates possible query params and provides
          data needed to build the report
        - Renderer(s) that generates the actual report based on the data from the serializer
        - optional: provide a filename for the report by overriding get_filename()
    """
    serializer_class = None
    renderer_classes = None

    def get_filename(self, request, validated_data):
        return None

    def get(self, request, format=None):
        serializer = self.serializer_class(data=request.query_params)
        if not serializer.is_valid():
            return Response(
                data=serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        response = Response(serializer.validated_data)

        filename = self.get_filename(request, serializer.validated_data)
        if filename:
            response['Content-Disposition'] = 'attachment; filename=%s' % filename
        return response

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)

        # use the first renderer from settings to display errors
        if response.status_code != 200:
            first_renderer = api_settings.DEFAULT_RENDERER_CLASSES[0]()
            response.accepted_renderer = first_renderer
            response.accepted_media_type = first_renderer.media_type

        return response


class DocxRenderer(renderers.BaseRenderer):
    media_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    format = 'docx'
    charset = None
    render_style = 'binary'
