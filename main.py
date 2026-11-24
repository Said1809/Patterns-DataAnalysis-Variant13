"""
Вариант 13. Интерактивный анализ набора данных.

Паттерны:
  ЛР1  — Одиночка (AppConfig), Строитель (AnalysisQueryBuilder)
  ЛР2  — Абстрактная фабрика (ChartFactory), Прототип (AnalysisQuery.clone)
  ЛР3  — Адаптер (Csv/Json → Dataset), Мост (Chart + ChartRenderer)
  ЛР4  — Компоновщик (MetricNode), Декоратор (ChartDecorator)
  ЛР5  — Фасад (AnalysisApp), Приспособленец (StyleFlyweightFactory)
  ЛР6  — Заместитель (LazyDatasetProxy)
  ЛР7  — Команда (AnalyzeCommand + история), Итератор (MetricTreeIterator)
  ЛР8  — Цепочка обязанностей (валидация запроса)
  ЛР9  — Посредник (UiMediator), Снимок (QueryMemento)
  ЛР10 — Наблюдатель (AnalysisSubject), Состояние (AppState)
  ЛР11 — Стратегия (AggregationStrategy), Шаблонный метод (AnalysisPipeline)
  ЛР12 — MVC (Model / View / Controller)
  ЛР13 — CQRS (CommandService / QueryService)
  ЛР14 — Repository (SalesRepository)
  ЛР15 — Future / ThreadPool (async chart export)
"""

from __future__ import annotations

import copy
import json
import threading
from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from typing import Any, Callable, Optional

import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_CSV = DATA_DIR / "sales.csv"


# ---------------------------------------------------------------------------
# ЛР1 — Одиночка
# ---------------------------------------------------------------------------

class AppConfig:
    """Глобальные настройки приложения (Singleton)."""

    _instance: Optional["AppConfig"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.window_title = "Интерактивный анализ набора данных"
            cls._instance.window_size = "1180x740"
            cls._instance.default_metric = "revenue"
            cls._instance.default_group = "region"
            cls._instance.default_agg = "sum"
        return cls._instance

    @classmethod
    def reset_for_tests(cls):
        cls._instance = None


# ---------------------------------------------------------------------------
# ЛР1 — Строитель + ЛР2 — Прототип + ЛР9 — Снимок
# ---------------------------------------------------------------------------

@dataclass
class AnalysisQuery:
    """Запрос анализа: фильтры, группировка и метрика."""

    metric: str = "revenue"
    group_by: str = "region"
    region: Optional[str] = None
    category: Optional[str] = None
    channel: Optional[str] = None
    chart_kind: str = "bar"
    aggregation: str = "sum"

    def clone(self) -> "AnalysisQuery":
        """Прототип: независимая копия запроса."""
        return copy.deepcopy(self)

    def create_memento(self) -> "QueryMemento":
        """Снимок текущего состояния запроса."""
        return QueryMemento(self.clone())

    def restore_memento(self, memento: "QueryMemento") -> None:
        saved = memento.query
        self.metric = saved.metric
        self.group_by = saved.group_by
        self.region = saved.region
        self.category = saved.category
        self.channel = saved.channel
        self.chart_kind = saved.chart_kind
        self.aggregation = saved.aggregation

    def describe(self) -> str:
        parts = [
            f"метрика={self.metric}",
            f"группа={self.group_by}",
            f"агрегация={self.aggregation}",
            f"график={self.chart_kind}",
        ]
        if self.region:
            parts.append(f"регион={self.region}")
        if self.category:
            parts.append(f"категория={self.category}")
        if self.channel:
            parts.append(f"канал={self.channel}")
        return ", ".join(parts)


@dataclass(frozen=True)
class QueryMemento:
    """Снимок запроса анализа (Memento)."""

    query: AnalysisQuery


class MementoCaretaker:
    """Хранит историю снимков запроса."""

    def __init__(self, limit: int = 20):
        self._history: list[QueryMemento] = []
        self._limit = limit

    def push(self, memento: QueryMemento) -> None:
        self._history.append(memento)
        if len(self._history) > self._limit:
            self._history.pop(0)

    def pop(self) -> Optional[QueryMemento]:
        if not self._history:
            return None
        return self._history.pop()

    def __len__(self) -> int:
        return len(self._history)


class AnalysisQueryBuilder:
    """Пошагово собирает AnalysisQuery."""

    def __init__(self):
        self._query = AnalysisQuery()

    def metric(self, name: str) -> "AnalysisQueryBuilder":
        self._query.metric = name
        return self

    def group_by(self, name: str) -> "AnalysisQueryBuilder":
        self._query.group_by = name
        return self

    def region(self, value: Optional[str]) -> "AnalysisQueryBuilder":
        self._query.region = value or None
        return self

    def category(self, value: Optional[str]) -> "AnalysisQueryBuilder":
        self._query.category = value or None
        return self

    def channel(self, value: Optional[str]) -> "AnalysisQueryBuilder":
        self._query.channel = value or None
        return self

    def chart(self, kind: str) -> "AnalysisQueryBuilder":
        self._query.chart_kind = kind
        return self

    def aggregation(self, name: str) -> "AnalysisQueryBuilder":
        self._query.aggregation = name
        return self

    def build(self) -> AnalysisQuery:
        return self._query.clone()


# ---------------------------------------------------------------------------
# ЛР3 — Адаптер: единый Dataset из CSV / JSON
# ---------------------------------------------------------------------------

class Dataset(ABC):
    """Целевой интерфейс набора данных."""

    @abstractmethod
    def as_dataframe(self) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def columns(self) -> list[str]:
        raise NotImplementedError


class CsvDatasetAdapter(Dataset):
    """Адаптирует CSV-файл к интерфейсу Dataset."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._df = pd.read_csv(self.path)

    def as_dataframe(self) -> pd.DataFrame:
        return self._df.copy()

    def columns(self) -> list[str]:
        return list(self._df.columns)


class JsonDatasetAdapter(Dataset):
    """Адаптирует JSON-файл к интерфейсу Dataset."""

    def __init__(self, path: Path):
        self.path = Path(path)
        with open(self.path, encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict) and "records" in payload:
            payload = payload["records"]
        self._df = pd.DataFrame(payload)

    def as_dataframe(self) -> pd.DataFrame:
        return self._df.copy()

    def columns(self) -> list[str]:
        return list(self._df.columns)


def open_raw_dataset(path: Path) -> Dataset:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return CsvDatasetAdapter(path)
    if suffix == ".json":
        return JsonDatasetAdapter(path)
    raise ValueError(f"Неподдерживаемый формат: {suffix}")


# ---------------------------------------------------------------------------
# ЛР6 — Заместитель: ленивая загрузка набора данных
# ---------------------------------------------------------------------------

class LazyDatasetProxy(Dataset):
    """Proxy: файл читается только при первом обращении к данным."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._real: Optional[Dataset] = None
        self.load_count = 0

    def _ensure_loaded(self) -> Dataset:
        if self._real is None:
            self._real = open_raw_dataset(self.path)
            self.load_count += 1
        return self._real

    @property
    def is_loaded(self) -> bool:
        return self._real is not None

    def as_dataframe(self) -> pd.DataFrame:
        return self._ensure_loaded().as_dataframe()

    def columns(self) -> list[str]:
        return self._ensure_loaded().columns()


def load_dataset(path: Path) -> Dataset:
    """Возвращает заместителя вместо немедленной загрузки."""
    return LazyDatasetProxy(path)


# ---------------------------------------------------------------------------
# ЛР14 — Repository
# ---------------------------------------------------------------------------

class SalesRepository(ABC):
    """Абстракция доступа к продажам."""

    @abstractmethod
    def load(self, path: Path) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def filter(self, df: pd.DataFrame, query: AnalysisQuery) -> pd.DataFrame:
        raise NotImplementedError


class FileSalesRepository(SalesRepository):
    """Репозиторий поверх файловых адаптеров / proxy."""

    def load(self, path: Path) -> pd.DataFrame:
        dataset = load_dataset(path)
        return dataset.as_dataframe()

    def filter(self, df: pd.DataFrame, query: AnalysisQuery) -> pd.DataFrame:
        return apply_query(df, query)


# ---------------------------------------------------------------------------
# ЛР5 — Приспособленец: общие стили графиков
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChartStyle:
    color: str
    edgecolor: str
    alpha: float
    title_size: int


class StyleFlyweightFactory:
    """Кэширует и переиспользует стили отрисовки."""

    def __init__(self):
        self._styles: dict[str, ChartStyle] = {}

    def get_style(self, name: str) -> ChartStyle:
        if name not in self._styles:
            presets = {
                "bar": ChartStyle("#3B82F6", "#1E3A8A", 0.9, 12),
                "line": ChartStyle("#10B981", "#065F46", 0.95, 12),
                "pie": ChartStyle("#F59E0B", "#92400E", 0.9, 12),
                "default": ChartStyle("#6366F1", "#312E81", 0.9, 12),
            }
            self._styles[name] = presets.get(name, presets["default"])
        return self._styles[name]


STYLE_FLYWEIGHTS = StyleFlyweightFactory()


# ---------------------------------------------------------------------------
# ЛР3 — Мост: абстракция графика + реализация отрисовки
# ---------------------------------------------------------------------------

class ChartRenderer(ABC):
    @abstractmethod
    def render(self, ax, labels: list[str], values: list[float], style: ChartStyle, title: str):
        raise NotImplementedError


class BarRenderer(ChartRenderer):
    def render(self, ax, labels, values, style, title):
        ax.bar(labels, values, color=style.color, edgecolor=style.edgecolor, alpha=style.alpha)
        ax.set_title(title, fontsize=style.title_size)
        ax.tick_params(axis="x", rotation=25)
        ax.set_ylabel("Значение")


class LineRenderer(ChartRenderer):
    def render(self, ax, labels, values, style, title):
        ax.plot(labels, values, marker="o", color=style.color, linewidth=2)
        ax.set_title(title, fontsize=style.title_size)
        ax.tick_params(axis="x", rotation=25)
        ax.set_ylabel("Значение")
        ax.grid(True, alpha=0.3)


class PieRenderer(ChartRenderer):
    def render(self, ax, labels, values, style, title):
        ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
        ax.set_title(title, fontsize=style.title_size)


class Chart(ABC):
    def __init__(self, renderer: ChartRenderer, style_name: str = "default"):
        self.renderer = renderer
        self.style = STYLE_FLYWEIGHTS.get_style(style_name)

    def draw(self, ax, labels: list[str], values: list[float], title: str):
        self.renderer.render(ax, labels, values, self.style, title)


class BarChart(Chart):
    def __init__(self):
        super().__init__(BarRenderer(), "bar")


class LineChart(Chart):
    def __init__(self):
        super().__init__(LineRenderer(), "line")


class PieChart(Chart):
    def __init__(self):
        super().__init__(PieRenderer(), "pie")


# ---------------------------------------------------------------------------
# ЛР2 — Абстрактная фабрика
# ---------------------------------------------------------------------------

class ChartFactory(ABC):
    @abstractmethod
    def create_bar(self) -> Chart:
        raise NotImplementedError

    @abstractmethod
    def create_line(self) -> Chart:
        raise NotImplementedError

    @abstractmethod
    def create_pie(self) -> Chart:
        raise NotImplementedError

    def create(self, kind: str) -> Chart:
        mapping = {
            "bar": self.create_bar,
            "line": self.create_line,
            "pie": self.create_pie,
        }
        if kind not in mapping:
            raise ValueError(f"Неизвестный тип графика: {kind}")
        return mapping[kind]()


class MatplotlibChartFactory(ChartFactory):
    def create_bar(self) -> Chart:
        return BarChart()

    def create_line(self) -> Chart:
        return LineChart()

    def create_pie(self) -> Chart:
        return PieChart()


# ---------------------------------------------------------------------------
# ЛР11 — Стратегия агрегации
# ---------------------------------------------------------------------------

class AggregationStrategy(ABC):
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def aggregate(self, series: pd.Series) -> float:
        raise NotImplementedError


class SumAggregation(AggregationStrategy):
    def name(self) -> str:
        return "sum"

    def aggregate(self, series: pd.Series) -> float:
        return float(series.sum())


class MeanAggregation(AggregationStrategy):
    def name(self) -> str:
        return "mean"

    def aggregate(self, series: pd.Series) -> float:
        return float(series.mean()) if len(series) else 0.0


class MaxAggregation(AggregationStrategy):
    def name(self) -> str:
        return "max"

    def aggregate(self, series: pd.Series) -> float:
        return float(series.max()) if len(series) else 0.0


AGG_STRATEGIES: dict[str, AggregationStrategy] = {
    "sum": SumAggregation(),
    "mean": MeanAggregation(),
    "max": MaxAggregation(),
}


# ---------------------------------------------------------------------------
# ЛР4 — Декоратор
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    labels: list[str]
    values: list[float]
    title: str
    extras: dict[str, Any] = field(default_factory=dict)


class ChartView(ABC):
    @abstractmethod
    def build(self, df: pd.DataFrame, query: AnalysisQuery) -> AnalysisResult:
        raise NotImplementedError

    @abstractmethod
    def draw(self, ax, result: AnalysisResult):
        raise NotImplementedError


class BasicChartView(ChartView):
    def __init__(self, factory: ChartFactory):
        self.factory = factory

    def build(self, df: pd.DataFrame, query: AnalysisQuery) -> AnalysisResult:
        filtered = apply_query(df, query)
        if filtered.empty:
            return AnalysisResult([], [], "Нет данных по запросу")
        strategy = AGG_STRATEGIES.get(query.aggregation, SumAggregation())
        grouped = filtered.groupby(query.group_by, dropna=False)[query.metric]
        values_map = {str(k): strategy.aggregate(g) for k, g in grouped}
        ordered = sorted(values_map.items(), key=lambda item: item[1], reverse=True)
        title = f"{query.metric} ({strategy.name()}) по {query.group_by}"
        return AnalysisResult(
            labels=[k for k, _ in ordered],
            values=[v for _, v in ordered],
            title=title,
        )

    def draw(self, ax, result: AnalysisResult):
        ax.clear()
        if not result.labels:
            ax.text(0.5, 0.5, result.title, ha="center", va="center")
            ax.axis("off")
            return
        kind = result.extras.get("chart_kind", "bar")
        chart = self.factory.create(kind)
        chart.draw(ax, result.labels, result.values, result.title)


class ChartDecorator(ChartView):
    def __init__(self, wrapped: ChartView):
        self._wrapped = wrapped

    def build(self, df: pd.DataFrame, query: AnalysisQuery) -> AnalysisResult:
        return self._wrapped.build(df, query)

    def draw(self, ax, result: AnalysisResult):
        self._wrapped.draw(ax, result)


class StatsOverlayDecorator(ChartDecorator):
    def build(self, df: pd.DataFrame, query: AnalysisQuery) -> AnalysisResult:
        result = self._wrapped.build(df, query)
        if result.values:
            result.extras["sum"] = sum(result.values)
            result.extras["avg"] = sum(result.values) / len(result.values)
            result.extras["max"] = max(result.values)
            result.title = f"{result.title} | Σ={result.extras['sum']:.0f}"
        result.extras["chart_kind"] = query.chart_kind
        return result

    def draw(self, ax, result: AnalysisResult):
        self._wrapped.draw(ax, result)
        if "avg" in result.extras and result.labels and result.extras.get("chart_kind") != "pie":
            ax.axhline(result.extras["avg"], color="#EF4444", linestyle="--", linewidth=1.2, label="среднее")
            ax.legend(loc="best")


# ---------------------------------------------------------------------------
# ЛР4 — Компоновщик + ЛР7 — Итератор
# ---------------------------------------------------------------------------

class MetricNode(ABC):
    @abstractmethod
    def evaluate(self, df: pd.DataFrame) -> float:
        raise NotImplementedError

    @abstractmethod
    def label(self) -> str:
        raise NotImplementedError


class LeafMetric(MetricNode):
    def __init__(self, name: str, column: str):
        self.name = name
        self.column = column

    def evaluate(self, df: pd.DataFrame) -> float:
        if self.column not in df.columns or df.empty:
            return 0.0
        return float(df[self.column].sum())

    def label(self) -> str:
        return self.name


class MetricGroup(MetricNode):
    def __init__(self, name: str):
        self.name = name
        self.children: list[MetricNode] = []

    def add(self, node: MetricNode) -> "MetricGroup":
        self.children.append(node)
        return self

    def evaluate(self, df: pd.DataFrame) -> float:
        return sum(child.evaluate(df) for child in self.children)

    def label(self) -> str:
        return self.name

    def __iter__(self) -> "MetricTreeIterator":
        return MetricTreeIterator(self)


class MetricTreeIterator:
    """Итератор обхода дерева метрик в глубину."""

    def __init__(self, root: MetricNode):
        self._stack: list[MetricNode] = [root]

    def __iter__(self) -> "MetricTreeIterator":
        return self

    def __next__(self) -> MetricNode:
        if not self._stack:
            raise StopIteration
        node = self._stack.pop()
        if isinstance(node, MetricGroup):
            self._stack.extend(reversed(node.children))
        return node


def build_default_metric_tree() -> MetricGroup:
    root = MetricGroup("Сводка")
    sales = MetricGroup("Продажи")
    sales.add(LeafMetric("Выручка", "revenue"))
    sales.add(LeafMetric("Единицы", "units"))
    root.add(sales)
    root.add(LeafMetric("Выручка (повтор)", "revenue"))
    return root


def apply_query(df: pd.DataFrame, query: AnalysisQuery) -> pd.DataFrame:
    result = df.copy()
    if query.region:
        result = result[result["region"] == query.region]
    if query.category:
        result = result[result["category"] == query.category]
    if query.channel:
        result = result[result["channel"] == query.channel]
    return result


# ---------------------------------------------------------------------------
# ЛР8 — Цепочка обязанностей: валидация запроса
# ---------------------------------------------------------------------------

class ValidationHandler(ABC):
    def __init__(self):
        self._next: Optional["ValidationHandler"] = None

    def set_next(self, handler: "ValidationHandler") -> "ValidationHandler":
        self._next = handler
        return handler

    def handle(self, df: pd.DataFrame, query: AnalysisQuery) -> Optional[str]:
        error = self.check(df, query)
        if error:
            return error
        if self._next:
            return self._next.handle(df, query)
        return None

    @abstractmethod
    def check(self, df: pd.DataFrame, query: AnalysisQuery) -> Optional[str]:
        raise NotImplementedError


class NotEmptyHandler(ValidationHandler):
    def check(self, df: pd.DataFrame, query: AnalysisQuery) -> Optional[str]:
        if df.empty:
            return "Набор данных пуст"
        return None


class MetricExistsHandler(ValidationHandler):
    def check(self, df: pd.DataFrame, query: AnalysisQuery) -> Optional[str]:
        if query.metric not in df.columns:
            return f"Метрика «{query.metric}» отсутствует в данных"
        return None


class GroupByExistsHandler(ValidationHandler):
    def check(self, df: pd.DataFrame, query: AnalysisQuery) -> Optional[str]:
        if query.group_by not in df.columns:
            return f"Поле группировки «{query.group_by}» отсутствует"
        return None


class AggregationHandler(ValidationHandler):
    def check(self, df: pd.DataFrame, query: AnalysisQuery) -> Optional[str]:
        if query.aggregation not in AGG_STRATEGIES:
            return f"Неизвестная агрегация: {query.aggregation}"
        return None


def build_validation_chain() -> ValidationHandler:
    head = NotEmptyHandler()
    head.set_next(MetricExistsHandler()).set_next(GroupByExistsHandler()).set_next(AggregationHandler())
    return head


# ---------------------------------------------------------------------------
# ЛР10 — Наблюдатель + Состояние
# ---------------------------------------------------------------------------

class AnalysisObserver(ABC):
    @abstractmethod
    def on_event(self, event: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError


class AnalysisSubject:
    def __init__(self):
        self._observers: list[AnalysisObserver] = []

    def attach(self, observer: AnalysisObserver) -> None:
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer: AnalysisObserver) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    def notify(self, event: str, **payload: Any) -> None:
        for observer in list(self._observers):
            observer.on_event(event, payload)


class AppState(ABC):
    def __init__(self, context: "Analyzer"):
        self.context = context

    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    def on_enter(self) -> None:
        self.context.notify("state_changed", state=self.name())


class IdleState(AppState):
    def name(self) -> str:
        return "idle"


class LoadedState(AppState):
    def name(self) -> str:
        return "loaded"


class AnalyzingState(AppState):
    def name(self) -> str:
        return "analyzing"


class ReadyState(AppState):
    def name(self) -> str:
        return "ready"


class ErrorState(AppState):
    def name(self) -> str:
        return "error"


# ---------------------------------------------------------------------------
# ЛР11 — Шаблонный метод: конвейер анализа
# ---------------------------------------------------------------------------

class AnalysisPipeline(ABC):
    """Скелет алгоритма анализа."""

    def run(self, df: pd.DataFrame, query: AnalysisQuery) -> AnalysisResult:
        self.before(df, query)
        validated = self.validate(df, query)
        if validated is not None:
            return AnalysisResult([], [], validated)
        filtered = self.filter_data(df, query)
        result = self.aggregate(filtered, query)
        return self.after(result, filtered, query)

    def before(self, df: pd.DataFrame, query: AnalysisQuery) -> None:
        return None

    @abstractmethod
    def validate(self, df: pd.DataFrame, query: AnalysisQuery) -> Optional[str]:
        raise NotImplementedError

    @abstractmethod
    def filter_data(self, df: pd.DataFrame, query: AnalysisQuery) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def aggregate(self, df: pd.DataFrame, query: AnalysisQuery) -> AnalysisResult:
        raise NotImplementedError

    def after(self, result: AnalysisResult, filtered: pd.DataFrame, query: AnalysisQuery) -> AnalysisResult:
        return result


class DefaultAnalysisPipeline(AnalysisPipeline):
    def __init__(self, view: ChartView, metric_tree: MetricGroup, validators: ValidationHandler):
        self.view = view
        self.metric_tree = metric_tree
        self.validators = validators

    def validate(self, df: pd.DataFrame, query: AnalysisQuery) -> Optional[str]:
        return self.validators.handle(df, query)

    def filter_data(self, df: pd.DataFrame, query: AnalysisQuery) -> pd.DataFrame:
        return apply_query(df, query)

    def aggregate(self, df: pd.DataFrame, query: AnalysisQuery) -> AnalysisResult:
        return self.view.build(df, query)

    def after(self, result: AnalysisResult, filtered: pd.DataFrame, query: AnalysisQuery) -> AnalysisResult:
        result.extras.setdefault("chart_kind", query.chart_kind)
        summary = {
            node.label(): node.evaluate(filtered)
            for node in MetricTreeIterator(self.metric_tree)
            if isinstance(node, LeafMetric)
        }
        result.extras["metric_tree"] = summary
        result.extras["rows"] = len(filtered)
        return result


# ---------------------------------------------------------------------------
# ЛР7 — Команда
# ---------------------------------------------------------------------------

class Command(ABC):
    @abstractmethod
    def execute(self) -> Any:
        raise NotImplementedError

    def undo(self) -> None:
        return None


class CommandHistory:
    def __init__(self):
        self._undo: list[Command] = []
        self._redo: list[Command] = []

    def push(self, command: Command) -> Any:
        result = command.execute()
        self._undo.append(command)
        self._redo.clear()
        return result

    def undo(self) -> bool:
        if not self._undo:
            return False
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        command = self._redo.pop()
        command.execute()
        self._undo.append(command)
        return True


class AnalyzeCommand(Command):
    """Команда запуска анализа с возможностью отката к прошлому запросу."""

    def __init__(self, analyzer: "Analyzer", query: AnalysisQuery):
        self.analyzer = analyzer
        self.query = query
        self._previous_query: Optional[AnalysisQuery] = None
        self._previous_result: Optional[AnalysisResult] = None
        self.result: Optional[AnalysisResult] = None

    def execute(self) -> AnalysisResult:
        self._previous_query = self.analyzer.last_query.clone() if self.analyzer.last_query else None
        self._previous_result = self.analyzer.last_result
        self.result = self.analyzer.run_pipeline(self.query)
        return self.result

    def undo(self) -> None:
        self.analyzer.last_query = self._previous_query
        self.analyzer.last_result = self._previous_result
        if self._previous_query is not None:
            self.analyzer.notify("analysis_undone", query=self._previous_query.describe())


# ---------------------------------------------------------------------------
# ЛР13 — CQRS
# ---------------------------------------------------------------------------

class AnalysisCommandService:
    """Сторона команд: загрузка данных и изменение состояния."""

    def __init__(self, analyzer: "Analyzer"):
        self.analyzer = analyzer

    def load_dataset(self, path: Path) -> int:
        return self.analyzer.load(path)

    def analyze(self, query: AnalysisQuery) -> AnalysisResult:
        return self.analyzer.run_pipeline(query)


class AnalysisQueryService:
    """Сторона запросов: только чтение агрегатов и метаданных."""

    def __init__(self, analyzer: "Analyzer"):
        self.analyzer = analyzer

    def current_result(self) -> Optional[AnalysisResult]:
        return self.analyzer.last_result

    def regions(self) -> list[str]:
        if self.analyzer.df.empty or "region" not in self.analyzer.df.columns:
            return []
        return sorted(self.analyzer.df["region"].dropna().unique().tolist())

    def describe_last(self) -> str:
        if self.analyzer.last_query is None:
            return "нет запросов"
        return self.analyzer.last_query.describe()


# ---------------------------------------------------------------------------
# ЛР15 — Future / ThreadPool
# ---------------------------------------------------------------------------

class ChartExportService:
    """Экспорт графиков в фоне через пул потоков."""

    def __init__(self, max_workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()

    def export_async(
        self,
        analyzer: "Analyzer",
        query: AnalysisQuery,
        output: Path,
        on_done: Optional[Callable[[Path], None]] = None,
    ) -> Future:
        def job() -> Path:
            local = Analyzer(analyzer.factory, repository=analyzer.repository)
            local.df = analyzer.df.copy()
            result = local.run_pipeline(query)
            fig = Figure(figsize=(7, 4), dpi=120)
            ax = fig.add_subplot(111)
            local.view.draw(ax, result)
            fig.tight_layout()
            output.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                fig.savefig(output, bbox_inches="tight")
            fig.clf()
            if on_done:
                on_done(output)
            return output

        return self._pool.submit(job)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# Модель (ЛР12 MVC) / аналитическое ядро
# ---------------------------------------------------------------------------

class Analyzer(AnalysisSubject):
    """Model: данные, конвейер анализа и состояние."""

    def __init__(
        self,
        factory: Optional[ChartFactory] = None,
        repository: Optional[SalesRepository] = None,
    ):
        super().__init__()
        self.factory = factory or MatplotlibChartFactory()
        self.repository = repository or FileSalesRepository()
        self.view: ChartView = StatsOverlayDecorator(BasicChartView(self.factory))
        self.metric_tree = build_default_metric_tree()
        self.validators = build_validation_chain()
        self.pipeline = DefaultAnalysisPipeline(self.view, self.metric_tree, self.validators)
        self.dataset: Optional[Dataset] = None
        self.df = pd.DataFrame()
        self.last_query: Optional[AnalysisQuery] = None
        self.last_result: Optional[AnalysisResult] = None
        self.commands = CommandHistory()
        self.mementos = MementoCaretaker()
        self.export_service = ChartExportService()
        self.command_service = AnalysisCommandService(self)
        self.query_service = AnalysisQueryService(self)
        self._state: AppState = IdleState(self)
        self._state.on_enter()

    def set_state(self, state: AppState) -> None:
        self._state = state
        self._state.on_enter()

    @property
    def state_name(self) -> str:
        return self._state.name()

    def load(self, path: Path) -> int:
        self.set_state(AnalyzingState(self))
        self.dataset = load_dataset(path)
        self.df = self.dataset.as_dataframe()
        self.set_state(LoadedState(self))
        self.notify(
            "dataset_loaded",
            path=str(path),
            rows=len(self.df),
            proxy=isinstance(self.dataset, LazyDatasetProxy),
        )
        return len(self.df)

    def run_pipeline(self, query: AnalysisQuery) -> AnalysisResult:
        self.set_state(AnalyzingState(self))
        result = self.pipeline.run(self.df, query)
        self.last_query = query
        self.last_result = result
        if result.labels or result.title.startswith("Нет"):
            self.set_state(ReadyState(self))
        else:
            self.set_state(ErrorState(self))
        self.notify("analysis_done", query=query.describe(), title=result.title)
        return result

    def run(self, query: AnalysisQuery) -> AnalysisResult:
        """Совместимость со старым API + команда."""
        command = AnalyzeCommand(self, query)
        return self.commands.push(command)


# ---------------------------------------------------------------------------
# ЛР9 — Посредник UI + ЛР12 — View / Controller
# ---------------------------------------------------------------------------

class UiMediator:
    """Посредник: виджеты общаются через него, а не напрямую."""

    def __init__(self):
        self.view: Optional["AnalysisWindow"] = None
        self.controller: Optional["AnalysisController"] = None

    def bind(self, view: "AnalysisWindow", controller: "AnalysisController") -> None:
        self.view = view
        self.controller = controller

    def request_analyze(self) -> None:
        if self.controller:
            self.controller.analyze()

    def request_undo(self) -> None:
        if self.controller:
            self.controller.undo()

    def request_restore_snapshot(self) -> None:
        if self.controller:
            self.controller.restore_snapshot()

    def publish_status(self, text: str) -> None:
        if self.view:
            self.view.set_status(text)

    def publish_summary(self, text: str) -> None:
        if self.view:
            self.view.set_summary(text)

    def publish_table(self, df: pd.DataFrame) -> None:
        if self.view:
            self.view.fill_table(df)

    def publish_chart(self, result: AnalysisResult) -> None:
        if self.view:
            self.view.draw_result(result)


class StatusObserver(AnalysisObserver):
    def __init__(self, mediator: UiMediator):
        self.mediator = mediator

    def on_event(self, event: str, payload: dict[str, Any]) -> None:
        if event == "state_changed":
            self.mediator.publish_status(f"Состояние: {payload.get('state')}")
        elif event == "dataset_loaded":
            proxy = "proxy" if payload.get("proxy") else "direct"
            self.mediator.publish_status(
                f"Загружено ({proxy}): {Path(payload['path']).name} — {payload['rows']} строк"
            )
        elif event == "analysis_done":
            self.mediator.publish_status(f"Готово: {payload.get('title')}")
        elif event == "analysis_undone":
            self.mediator.publish_status(f"Отмена анализа: {payload.get('query')}")


class AnalysisController:
    """Controller (MVC): реакция на действия пользователя."""

    def __init__(self, model: Analyzer, mediator: UiMediator):
        self.model = model
        self.mediator = mediator
        self.model.attach(StatusObserver(mediator))

    def load_path(self, path: Path) -> None:
        try:
            self.model.command_service.load_dataset(path)
        except Exception as exc:
            messagebox.showerror("Ошибка загрузки", str(exc))
            self.model.set_state(ErrorState(self.model))
            return
        self.mediator.publish_table(self.model.df)
        if self.mediator.view:
            self.mediator.view.refresh_filters()
        self.analyze()

    def current_query_from_view(self) -> AnalysisQuery:
        assert self.mediator.view is not None
        return self.mediator.view.build_query()

    def analyze(self) -> None:
        if self.model.df.empty:
            messagebox.showinfo("Нет данных", "Сначала загрузите CSV или JSON")
            return
        view = self.mediator.view
        assert view is not None
        query = view.build_query()
        self.model.mementos.push(query.create_memento())
        result = self.model.run(query)
        filtered = self.model.repository.filter(self.model.df, query)
        self.mediator.publish_table(filtered)
        lines = [
            f"Запрос: {query.describe()}",
            f"Строк после фильтра: {result.extras.get('rows', len(filtered))}",
            f"Состояние: {self.model.state_name}",
        ]
        if "sum" in result.extras:
            lines.append(
                f"Статистика декоратора: сумма={result.extras['sum']:.2f}, "
                f"среднее={result.extras['avg']:.2f}, макс={result.extras['max']:.2f}"
            )
        tree = result.extras.get("metric_tree", {})
        if tree:
            lines.append("Дерево метрик (итератор): " + ", ".join(f"{k}={v:.0f}" for k, v in tree.items()))
        self.mediator.publish_summary("\n".join(lines))
        self.mediator.publish_chart(result)

    def undo(self) -> None:
        if not self.model.commands.undo():
            messagebox.showinfo("Отмена", "Нечего отменять")
            return
        result = self.model.last_result
        query = self.model.last_query
        if query is None or result is None:
            self.mediator.publish_status("История команд пуста после отмены")
            return
        if self.mediator.view:
            self.mediator.view.apply_query_to_controls(query)
        filtered = self.model.repository.filter(self.model.df, query)
        self.mediator.publish_table(filtered)
        self.mediator.publish_chart(result)
        self.mediator.publish_summary(f"Откат к запросу: {query.describe()}")

    def save_snapshot(self) -> None:
        query = self.current_query_from_view()
        self.model.mementos.push(query.create_memento())
        self.mediator.publish_status(f"Снимок сохранён ({len(self.model.mementos)} в истории)")

    def restore_snapshot(self) -> None:
        memento = self.model.mementos.pop()
        if memento is None:
            messagebox.showinfo("Снимок", "История снимков пуста")
            return
        if self.mediator.view:
            self.mediator.view.apply_query_to_controls(memento.query)
        self.analyze()
        self.mediator.publish_status("Снимок восстановлен")

    def export_chart_async(self, path: Path) -> None:
        query = self.current_query_from_view()

        def done(output: Path) -> None:
            # колбэк из рабочего потока — обновление UI через after
            if self.mediator.view:
                self.mediator.view.root.after(
                    0, lambda: self.mediator.publish_status(f"Фоновый экспорт готов: {output}")
                )

        future = self.model.export_service.export_async(self.model, query, path, on_done=done)
        self.mediator.publish_status("Экспорт графика запущен в ThreadPool...")
        future.add_done_callback(lambda f: f.result())


class AnalysisWindow(AnalysisObserver):
    """View (MVC): только отображение и сбор ввода."""

    def __init__(self, model: Analyzer, mediator: UiMediator):
        self.config = AppConfig()
        self.model = model
        self.mediator = mediator
        self.root = tk.Tk()
        self.root.title(self.config.window_title)
        self.root.geometry(self.config.window_size)

        self.region_var = tk.StringVar(value="Все")
        self.category_var = tk.StringVar(value="Все")
        self.channel_var = tk.StringVar(value="Все")
        self.metric_var = tk.StringVar(value=self.config.default_metric)
        self.group_var = tk.StringVar(value=self.config.default_group)
        self.chart_var = tk.StringVar(value="bar")
        self.agg_var = tk.StringVar(value=self.config.default_agg)
        self.status_var = tk.StringVar(value="Загрузите набор данных")

        self._prototype_query: Optional[AnalysisQuery] = None
        self._build_ui()
        self.model.attach(self)

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Button(top, text="Открыть CSV/JSON", command=self._open_file).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="Анализ", command=lambda: self.mediator.request_analyze()).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="Отмена", command=lambda: self.mediator.request_undo()).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="Снимок", command=self._save_snapshot).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="Восстановить", command=lambda: self.mediator.request_restore_snapshot()).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(top, text="Прототип↓", command=self._save_prototype).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="Прототип↑", command=self._load_prototype).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="Сохранить график", command=self._save_chart).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="Фон. экспорт", command=self._export_async).pack(side=tk.LEFT, padx=3)

        filters = ttk.LabelFrame(self.root, text="Параметры запроса", padding=8)
        filters.pack(fill=tk.X, padx=8, pady=4)

        self.region_combo = self._add_combo(filters, "Регион", self.region_var, 0)
        self.category_combo = self._add_combo(filters, "Категория", self.category_var, 1)
        self.channel_combo = self._add_combo(filters, "Канал", self.channel_var, 2)
        self._add_combo(filters, "Метрика", self.metric_var, 3, values=["revenue", "units"])
        self._add_combo(filters, "Группировка", self.group_var, 4, values=["region", "category", "channel", "product"])
        self._add_combo(filters, "Агрегация", self.agg_var, 5, values=["sum", "mean", "max"])
        self._add_combo(filters, "График", self.chart_var, 6, values=["bar", "line", "pie"])

        body = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=2)

        self.table = ttk.Treeview(left, show="headings", height=18)
        self.table.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.table.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.table.configure(yscrollcommand=scroll.set)

        self.summary = tk.Text(right, height=7, wrap=tk.WORD)
        self.summary.pack(fill=tk.X)

        self.figure = Figure(figsize=(6, 4), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        ttk.Label(self.root, textvariable=self.status_var).pack(fill=tk.X, padx=8, pady=4)

    def _add_combo(self, parent, label, variable, column, values=None):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, padx=6, sticky="w")
        ttk.Label(frame, text=label).pack(anchor="w")
        combo = ttk.Combobox(frame, textvariable=variable, width=13, state="readonly")
        if values:
            combo["values"] = values
        combo.pack()
        return combo

    def on_event(self, event: str, payload: dict[str, Any]) -> None:
        # View также подписан: достаточно обновить статус через mediator-observer.
        return None

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def set_summary(self, text: str) -> None:
        self.summary.delete("1.0", tk.END)
        self.summary.insert(tk.END, text)

    def fill_table(self, df: pd.DataFrame) -> None:
        self.table.delete(*self.table.get_children())
        cols = list(df.columns)
        self.table["columns"] = cols
        for col in cols:
            self.table.heading(col, text=col)
            self.table.column(col, width=90, anchor="center")
        for _, row in df.head(200).iterrows():
            self.table.insert("", tk.END, values=[row[c] for c in cols])

    def draw_result(self, result: AnalysisResult) -> None:
        self.model.view.draw(self.ax, result)
        self.figure.tight_layout()
        self.canvas.draw()

    def refresh_filters(self) -> None:
        df = self.model.df
        self.region_combo["values"] = ["Все"] + sorted(df["region"].dropna().unique().tolist())
        self.category_combo["values"] = ["Все"] + sorted(df["category"].dropna().unique().tolist())
        self.channel_combo["values"] = ["Все"] + sorted(df["channel"].dropna().unique().tolist())
        self.region_var.set("Все")
        self.category_var.set("Все")
        self.channel_var.set("Все")

    def build_query(self) -> AnalysisQuery:
        return (
            AnalysisQueryBuilder()
            .metric(self.metric_var.get())
            .group_by(self.group_var.get())
            .chart(self.chart_var.get())
            .aggregation(self.agg_var.get())
            .region(None if self.region_var.get() == "Все" else self.region_var.get())
            .category(None if self.category_var.get() == "Все" else self.category_var.get())
            .channel(None if self.channel_var.get() == "Все" else self.channel_var.get())
            .build()
        )

    def apply_query_to_controls(self, query: AnalysisQuery) -> None:
        self.metric_var.set(query.metric)
        self.group_var.set(query.group_by)
        self.chart_var.set(query.chart_kind)
        self.agg_var.set(query.aggregation)
        self.region_var.set(query.region or "Все")
        self.category_var.set(query.category or "Все")
        self.channel_var.set(query.channel or "Все")

    def _open_file(self):
        path = filedialog.askopenfilename(
            title="Выберите набор данных",
            filetypes=[("Data files", "*.csv *.json"), ("CSV", "*.csv"), ("JSON", "*.json")],
        )
        if path and self.mediator.controller:
            self.mediator.controller.load_path(Path(path))

    def _save_snapshot(self):
        if self.mediator.controller:
            self.mediator.controller.save_snapshot()

    def _save_prototype(self):
        self._prototype_query = self.build_query().clone()
        self.set_status(f"Прототип сохранён: {self._prototype_query.describe()}")

    def _load_prototype(self):
        if self._prototype_query is None:
            messagebox.showinfo("Прототип", "Сначала сохраните прототип запроса")
            return
        self.apply_query_to_controls(self._prototype_query.clone())
        self.mediator.request_analyze()
        self.set_status("Прототип загружен и применён")

    def _save_chart(self):
        if self.model.last_result is None:
            messagebox.showinfo("График", "Сначала выполните анализ")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
            initialfile="analysis-result.png",
        )
        if path:
            self.figure.savefig(path, dpi=140, bbox_inches="tight")
            self.set_status(f"График сохранён: {path}")

    def _export_async(self):
        if self.model.df.empty:
            messagebox.showinfo("Экспорт", "Сначала загрузите данные")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png")],
            initialfile="analysis-async.png",
        )
        if path and self.mediator.controller:
            self.mediator.controller.export_chart_async(Path(path))

    def run(self):
        self.root.mainloop()
        self.model.export_service.shutdown()


# ---------------------------------------------------------------------------
# ЛР5 — Фасад
# ---------------------------------------------------------------------------

class AnalysisApp:
    """Упрощённый интерфейс запуска приложения анализа данных."""

    def __init__(self, data_path: Optional[Path] = None):
        self.model = Analyzer(MatplotlibChartFactory(), FileSalesRepository())
        self.mediator = UiMediator()
        self.controller = AnalysisController(self.model, self.mediator)
        self.window = AnalysisWindow(self.model, self.mediator)
        self.mediator.bind(self.window, self.controller)
        path = Path(data_path) if data_path else DEFAULT_CSV
        if path.exists():
            self.controller.load_path(path)

    def run(self):
        self.window.run()


def export_demo_chart(output: Path, query: Optional[AnalysisQuery] = None) -> Path:
    """Вспомогательный экспорт графика без GUI (для отчётов)."""
    analyzer = Analyzer()
    analyzer.load(DEFAULT_CSV)
    query = query or (
        AnalysisQueryBuilder()
        .metric("revenue")
        .group_by("region")
        .chart("bar")
        .aggregation("sum")
        .build()
    )
    result = analyzer.run_pipeline(query)
    fig = Figure(figsize=(7, 4), dpi=120)
    ax = fig.add_subplot(111)
    analyzer.view.draw(ax, result)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    return output


if __name__ == "__main__":
    AnalysisApp().run()
