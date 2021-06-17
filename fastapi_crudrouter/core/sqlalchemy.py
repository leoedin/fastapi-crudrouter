from typing import Any, Callable, List, Dict, Type, Generator, Optional, Union

from fastapi import Depends, HTTPException, Response, Query

from . import CRUDGenerator, NOT_FOUND, _utils
from ._types import DEPENDENCIES, PAGINATION, PYDANTIC_SCHEMA as SCHEMA
import json

try:
    from sqlalchemy import or_
    from sqlalchemy.orm import Session
    from sqlalchemy.ext.declarative import DeclarativeMeta as Model
    from sqlalchemy.exc import IntegrityError
except ImportError:
    Model: Any = None  # type: ignore
    sqlalchemy_installed = False
else:
    sqlalchemy_installed = True
    Session = Callable[..., Generator[Session, Any, None]]


class SQLAlchemyCRUDRouter(CRUDGenerator[SCHEMA]):
    def __init__(
        self,
        schema: Type[SCHEMA],
        db_model: Model,
        db: "Session",
        create_schema: Optional[Type[SCHEMA]] = None,
        update_schema: Optional[Type[SCHEMA]] = None,
        prefix: Optional[str] = None,
        tags: Optional[List[str]] = None,
        paginate: Optional[int] = None,
        get_all_route: Union[bool, DEPENDENCIES] = True,
        get_one_route: Union[bool, DEPENDENCIES] = True,
        create_route: Union[bool, DEPENDENCIES] = True,
        update_route: Union[bool, DEPENDENCIES] = True,
        delete_one_route: Union[bool, DEPENDENCIES] = True,
        delete_all_route: Union[bool, DEPENDENCIES] = True,
        **kwargs: Any
    ) -> None:
        assert (
            sqlalchemy_installed
        ), "SQLAlchemy must be installed to use the SQLAlchemyCRUDRouter."

        self.db_model = db_model
        self.db_func = db
        self._pk: str = db_model.__table__.primary_key.columns.keys()[0]
        self._pk_type: type = _utils.get_pk_type(schema, self._pk)

        super().__init__(
            schema=schema,
            create_schema=create_schema,
            update_schema=update_schema,
            prefix=prefix or db_model.__tablename__,
            tags=tags,
            paginate=paginate,
            get_all_route=get_all_route,
            get_one_route=get_one_route,
            create_route=create_route,
            update_route=update_route,
            delete_one_route=delete_one_route,
            delete_all_route=delete_all_route,
            **kwargs
        )

    def _get_all(self, *args: Any, **kwargs: Any) -> Callable[..., List[Model]]:
        def route(
            response: Response,
            db: Session = Depends(self.db_func),
            pagination: PAGINATION = self.pagination,
            filter: str = None,
            sort: str = None
        ) -> List[Model]:
            skip, limit = pagination.get("skip"), pagination.get("limit")
            #sort = json.loads(sort)

            # Get the raw query first
            query = db.query(self.db_model)

            # Then, if we have criteria, filter the raw query
            if filter:
                # Filter is of form {"id":["44022001-a4e1-4434-a0be-85b408903d76","1d0943fc-3046-4158-985b-ae6b2aeb82b7"]}
                # We take it as a string and parse to JSON here, as I couldn't get FastAPI to parse it as JSON as a query param
                filter = json.loads(filter)

                # Then loop through each item in the filter dict
                for attr, value in filter.items():
                    # Each item is given to us as an array, so we loop through the array and create an OR query based on it
                    query = query.filter( or_(getattr(self.db_model, attr) == v for v in value) )

            # The total possible is the query count
            total: int = query.count()

            # And then apply the limit, offset, and get everything
            db_models: List[Model] = query.limit(limit).offset(skip).all()

            response.headers["Content-Range"] = f"{skip}-{skip + len(db_models) - 1}/{total}"

            return db_models

        return route

    def _get_one(self, *args: Any, **kwargs: Any) -> Callable[..., Model]:
        def route(
            item_id: self._pk_type, db: Session = Depends(self.db_func)  # type: ignore
        ) -> Model:
            model: Model = db.query(self.db_model).get(item_id)

            if model:
                return model
            else:
                raise NOT_FOUND

        return route

    def _create(self, *args: Any, **kwargs: Any) -> Callable[..., Model]:
        def route(
            model: self.create_schema,  # type: ignore
            db: Session = Depends(self.db_func),
        ) -> Model:
            try:
                db_model: Model = self.db_model(**model.dict())
                db.add(db_model)
                db.commit()
                db.refresh(db_model)
                return db_model
            except IntegrityError:
                db.rollback()
                raise HTTPException(422, "Key already exists")

        return route

    def _update(self, *args: Any, **kwargs: Any) -> Callable[..., Model]:
        def route(
            item_id: self._pk_type,  # type: ignore
            model: self.update_schema,  # type: ignore
            db: Session = Depends(self.db_func),
        ) -> Model:
            try:
                db_model: Model = self._get_one()(item_id, db)

                for key, value in model.dict(exclude={self._pk}).items():
                    if hasattr(db_model, key):
                        setattr(db_model, key, value)

                db.commit()
                db.refresh(db_model)

                return db_model
            except IntegrityError as e:
                db.rollback()
                raise HTTPException(422, ", ".join(e.args))

        return route

    def _delete_all(self, *args: Any, **kwargs: Any) -> Callable[..., List[Model]]:
        def route(db: Session = Depends(self.db_func)) -> List[Model]:
            db.query(self.db_model).delete()
            db.commit()

            return self._get_all()(db=db, pagination={"skip": 0, "limit": None})

        return route

    def _delete_one(self, *args: Any, **kwargs: Any) -> Callable[..., Model]:
        def route(
            item_id: self._pk_type, db: Session = Depends(self.db_func)  # type: ignore
        ) -> Model:
            db_model: Model = self._get_one()(item_id, db)
            db.delete(db_model)
            db.commit()

            return db_model

        return route
