CREATE TABLE table_card (
    product_id     bigint PRIMARY KEY,
    title          text        NOT NULL,
    subject_codes  text[]      NOT NULL,
    frequency      smallint    NOT NULL,
    start_date     date,
    end_date       date,
    card_text      text        NOT NULL,            -- what gets embedded (~600 tokens)
    tsv            tsvector    NOT NULL,            -- title + every member name
    embedding      vector(1024),                    -- NULL until embedded (step 2.2)
    metadata_hash  text        NOT NULL,            -- sha256(card + fts source + model)
    indexed_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX table_card_tsv ON table_card USING gin (tsv);

CREATE TABLE member (
    product_id          bigint  NOT NULL REFERENCES table_card ON DELETE CASCADE,
    dimension_position  smallint NOT NULL,
    member_id           integer NOT NULL,
    parent_id           integer,
    name                text    NOT NULL,
    terminated          boolean NOT NULL DEFAULT false,
    PRIMARY KEY (product_id, dimension_position, member_id)
);
