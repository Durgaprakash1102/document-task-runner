from rest_framework import serializers


class TaskSubmissionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    depends_on = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        default=list,
    )
    max_retries = serializers.IntegerField(
        required=False,
        min_value=0,
        default=3,
    )
    failure_probability = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        default=0.1,
    )
    min_duration = serializers.FloatField(
        required=False,
        min_value=0.0,
        default=1.0,
    )
    max_duration = serializers.FloatField(
        required=False,
        min_value=0.0,
        default=3.0,
    )

    def validate(self, attrs):
        if attrs["min_duration"] > attrs["max_duration"]:
            raise serializers.ValidationError(
                "min_duration cannot be greater than max_duration."
            )

        return attrs


class WorkflowSubmissionSerializer(serializers.Serializer):
    tasks = TaskSubmissionSerializer(
        many=True,
        allow_empty=False,
    )