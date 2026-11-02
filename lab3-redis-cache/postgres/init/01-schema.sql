CREATE TABLE authors (
    id       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name     text NOT NULL,
    country  text NOT NULL
);

CREATE TABLE books (
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title       text NOT NULL,
    author_id   integer NOT NULL REFERENCES authors(id),
    genre       text NOT NULL,
    year        smallint NOT NULL,
    price       numeric(8,2) NOT NULL CHECK (price > 0),
    isbn        text NOT NULL UNIQUE,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reviews (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id     integer NOT NULL REFERENCES books(id),
    rating      smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
    body        text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);
