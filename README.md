# Вариант 13 — Интерактивный анализ набора данных

Приложение для загрузки CSV/JSON, фильтрации продаж, построения сводок и графиков. Реализованы паттерны лабораторных работ 1–15.

## Запуск

```bash
pip install -r requirements.txt
python main.py
```

По умолчанию загружается `data/sales.csv`. Можно открыть свой CSV/JSON кнопкой «Открыть CSV/JSON».

## Управление

- фильтры: регион, категория, канал
- метрика: `revenue` / `units`
- агрегация: `sum` / `mean` / `max` (Strategy)
- группировка: region / category / channel / product
- тип графика: bar / line / pie
- «Отмена» — откат команды анализа (Command)
- «Снимок» / «Восстановить» — Memento запроса
- «Прототип↓ / ↑» — клонирование запроса (Prototype)
- «Сохранить график» — синхронный PNG
- «Фон. экспорт» — PNG через ThreadPool / Future

## Паттерны

| ЛР | Паттерны | Где в коде |
|----|----------|------------|
| 1 | Singleton, Builder | `AppConfig`, `AnalysisQueryBuilder` |
| 2 | Abstract Factory, Prototype | `ChartFactory`, `AnalysisQuery.clone` |
| 3 | Adapter, Bridge | `Csv/JsonDatasetAdapter`, `Chart` + `ChartRenderer` |
| 4 | Composite, Decorator | `MetricGroup`, `StatsOverlayDecorator` |
| 5 | Facade, Flyweight | `AnalysisApp`, `StyleFlyweightFactory` |
| 6 | Proxy | `LazyDatasetProxy` |
| 7 | Command, Iterator | `AnalyzeCommand`, `MetricTreeIterator` |
| 8 | Chain of Responsibility | `ValidationHandler` |
| 9 | Mediator, Memento | `UiMediator`, `QueryMemento` |
| 10 | Observer, State | `AnalysisSubject`, `AppState` |
| 11 | Strategy, Template Method | `AggregationStrategy`, `AnalysisPipeline` |
| 12 | MVC | `Analyzer` / `AnalysisWindow` / `AnalysisController` |
| 13 | CQRS | `AnalysisCommandService`, `AnalysisQueryService` |
| 14 | Repository | `SalesRepository`, `FileSalesRepository` |
| 15 | Future / Thread Pool | `ChartExportService` |

Отчёты: `docs/lab1.md` … `docs/lab15.md`.
