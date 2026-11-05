SELECT setseed(0.42);

INSERT INTO authors (name, country)
SELECT 'Author ' || g,
       (ARRAY['RU','KZ','BY','SA','SY','US','GB','DE','FR','JP','CN','BR'])[1 + (g % 12)]
FROM generate_series(1, 5000) AS g;

INSERT INTO books (title, author_id, genre, year, price, isbn)
SELECT 'Book #' || g || ' ' || (ARRAY['Shadows','River','Code','Empire','Garden','Machine','Silence','North','Storm','Light'])[1 + (g % 10)],
       1 + (g * 7919) % 5000,
       (ARRAY['fantasy','science','history','detective','romance','poetry',
              'biography','horror','children','business','philosophy','travel'])[1 + (g % 12)],
       1950 + (g % 76),
       round((5 + random() * 95)::numeric, 2),
       '978-' || lpad(g::text, 9, '0')
FROM generate_series(1, 100000) AS g;

INSERT INTO reviews (book_id, rating, body, created_at)
SELECT b,
       1 + ((b * 7 + floor(random() * 3)::int) % 5),
       'review ' || g,
       now() - (random() * interval '730 days')
FROM (SELECT g, 1 + floor(99999 * power(random(), 3))::int AS b
      FROM generate_series(1, 2000000) AS g) s;

CREATE INDEX reviews_book_id_idx ON reviews (book_id);
CREATE INDEX books_genre_idx ON books (genre);
ANALYZE;
