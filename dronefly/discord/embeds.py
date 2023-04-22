import copy

from pyinaturalist.constants import JsonResponse
from pyinaturalist.models import Taxon

from dronefly.core.formatters.generic import (
    format_taxon_names,
    TaxonFormatter as CoreTaxonFormatter,
)
from dronefly.core.query.query import QueryResponse
from dronefly.core.utils import obs_url_from_v1

class TaxonFormatter(CoreTaxonFormatter):
    def format(
        self,
        with_ancestors: bool = True
    ):
        """Format the taxon as markdown.

        with_ancestors: bool, optional
            When False, omit ancestors
        """
        description = self.format_taxon_description()
        if with_ancestors and self.taxon.ancestors:
            description += (
                " in: "
                + format_taxon_names(
                    self.taxon.ancestors,
                    hierarchy=True,
                    max_len=self.max_len,
                )
            )
        else:
            description += "."
        return description


class QueryResponseFormatter(TaxonFormatter):
    def __init__(
            self,
            query_response: QueryResponse,
            observations: JsonResponse=None,
            **kwargs,
        ):
        super().__init__(**kwargs)
        self.query_response = query_response
        self.observations = observations
        self.obs_count_formatter = self.ObsCountFormatter(query_response.taxon, query_response, observations)

    class ObsCountFormatter(TaxonFormatter.ObsCountFormatter):
        def __init__(self, taxon: Taxon, query_response: QueryResponse=None, observations: JsonResponse=None):
            super().__init__(taxon)
            self.query_response = query_response
            self.observations = observations

        def count(self):
            if self.observations:
                count = self.observations.get('total_results')
            else:
                count = self.taxon.observations_count
            return count

        def url(self):
            return obs_url_from_v1(self.query_response.obs_args())

        def description(self):
            count = self.link()
            count_str = "uncounted" if count is None else str(count)
            adjectives = self.query_response.adjectives # rg, nid, etc.
            query_without_taxon = copy.copy(self.query_response)
            query_without_taxon.taxon = None
            description = [
                count_str,
                *adjectives,
                p.plural('observation', count),
            ]
            filter = query_without_taxon.obs_query_description(with_adjectives=False) # place, prj, etc.
            if filter:
                description.append(filter)
            return " ".join(description)
