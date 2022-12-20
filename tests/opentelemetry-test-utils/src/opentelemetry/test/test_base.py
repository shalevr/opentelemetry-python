# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import unittest
from contextlib import contextmanager
from typing import Optional, Tuple, Union

from opentelemetry import metrics as metrics_api
from opentelemetry import trace as trace_api
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics._internal.point import Metric
from opentelemetry.sdk.metrics.export import (
    HistogramDataPoint,
    InMemoryMetricReader,
    MetricReader,
    NumberDataPoint,
)
from opentelemetry.sdk.trace import TracerProvider, export
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.test.globals_test import (
    reset_metrics_globals,
    reset_trace_globals,
)


class TestBase(unittest.TestCase):
    # pylint: disable=C0103

    def setUp(self):
        super().setUp()
        result = self.create_tracer_provider()
        self.tracer_provider, self.memory_exporter = result
        # This is done because set_tracer_provider cannot override the
        # current tracer provider.
        reset_trace_globals()
        trace_api.set_tracer_provider(self.tracer_provider)

        self.memory_exporter.clear()
        # This is done because set_meter_provider cannot override the
        # current meter provider.
        reset_metrics_globals()
        (
            self.meter_provider,
            self.memory_metrics_reader,
        ) = self.create_meter_provider()
        metrics_api.set_meter_provider(self.meter_provider)

    def tearDown(self):
        super().tearDown()
        reset_trace_globals()
        reset_metrics_globals()

    def get_finished_spans(self):
        return FinishedTestSpans(
            self, self.memory_exporter.get_finished_spans()
        )

    def assertEqualSpanInstrumentationInfo(self, span, module):
        self.assertEqual(span.instrumentation_info.name, module.__name__)
        self.assertEqual(span.instrumentation_info.version, module.__version__)

    def assertSpanHasAttributes(self, span, attributes):
        for key, val in attributes.items():
            self.assertIn(key, span.attributes)
            self.assertEqual(val, span.attributes[key])

    def sorted_spans(self, spans):  # pylint: disable=R0201
        """
        Sorts spans by span creation time.

        Note: This method should not be used to sort spans in a deterministic way as the
        order depends on timing precision provided by the platform.
        """
        return sorted(
            spans,
            key=lambda s: s._start_time,  # pylint: disable=W0212
            reverse=True,
        )

    def sorted_metrics(self, metrics):  # pylint: disable=R0201
        """
        Sorts metrics by metric name.
        """
        return sorted(
            metrics,
            key=lambda m: m.name,
        )

    def get_sorted_metrics(self):
        resource_metrics = (
            self.memory_metrics_reader.get_metrics_data().resource_metrics
        )

        all_metrics = []
        for metrics in resource_metrics:
            for scope_metrics in metrics.scope_metrics:
                all_metrics.extend(scope_metrics.metrics)

        return self.sorted_metrics(all_metrics)

    def assert_metric_expected(
        self,
        metric: Metric,
        expected_value: Union[int, float],
        expected_attributes: dict,
        est_delta: Optional[float] = None,
    ):
        data_point = next(iter(metric.data.data_points))

        if isinstance(data_point, HistogramDataPoint):
            self.assertEqual(
                data_point.count,
                1,
            )
            if est_delta is None:
                self.assertEqual(
                    data_point.sum,
                    expected_value,
                )
            else:
                self.assertAlmostEqual(
                    data_point.sum,
                    expected_value,
                    delta=est_delta,
                )
        elif isinstance(data_point, NumberDataPoint):
            self.assertEqual(
                data_point.value,
                expected_value,
            )

        self.assertDictEqual(
            expected_attributes,
            dict(data_point.attributes),
        )

    @staticmethod
    def create_tracer_provider(**kwargs):
        """Helper to create a configured tracer provider.

        Creates and configures a `TracerProvider` with a
        `SimpleSpanProcessor` and a `InMemorySpanExporter`.
        All the parameters passed are forwarded to the TracerProvider
        constructor.

        Returns:
            A list with the tracer provider in the first element and the
            in-memory span exporter in the second.
        """
        tracer_provider = TracerProvider(**kwargs)
        memory_exporter = InMemorySpanExporter()
        span_processor = export.SimpleSpanProcessor(memory_exporter)
        tracer_provider.add_span_processor(span_processor)

        return tracer_provider, memory_exporter

    @staticmethod
    def create_meter_provider(**kwargs) -> Tuple[MeterProvider, MetricReader]:
        """Helper to create a configured meter provider
        Creates a `MeterProvider` and an `InMemoryMetricReader`.
        Returns:
            A tuple with the meter provider in the first element and the
            in-memory metrics exporter in the second
        """
        memory_reader = InMemoryMetricReader()
        metric_readers = kwargs.get("metric_readers", [])
        metric_readers.append(memory_reader)
        kwargs["metric_readers"] = metric_readers
        meter_provider = MeterProvider(**kwargs)
        return meter_provider, memory_reader

    @staticmethod
    @contextmanager
    def disable_logging(highest_level=logging.CRITICAL):
        logging.disable(highest_level)

        try:
            yield
        finally:
            logging.disable(logging.NOTSET)


class FinishedTestSpans(list):
    def __init__(self, test, spans):
        super().__init__(spans)
        self.test = test

    def by_name(self, name):
        for span in self:
            if span.name == name:
                return span
        self.test.fail(f"Did not find span with name {name}")
        return None

    def by_attr(self, key, value):
        for span in self:
            if span.attributes.get(key) == value:
                return span
        self.test.fail(f"Did not find span with attrs {key}={value}")
        return None
